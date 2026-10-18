"""Leitura de precos dos encartes ja baixados.

Tres dos cinco mercados publicam PDF com texto real (Atacadao, Covabra e Savegnago):
o preco sai com fidelidade de 100%, sem OCR. Assai e Examine publicam imagem (JPEG):
ai o texto vem de OCR (tesseract) e a leitura e parcial - ver `Ocr` e o README.

Formato do texto nos tres mercados com camada de texto (encartes de 15/10/2026):

    Azeite de Oliva           <- descricao do item (uma ou mais linhas)
    Andorinha
    Vidro com 500ml
    PREÇO VAREJO/ATACADO      <- cabecalho de coluna, repetido por item
    R$20,90                   <- precos logo depois da descricao
    R$18,90
    R$22,90

Covabra escreve `R$ 32 , 90` (espacos em volta da virgula) e Savegnago escreve o preco
sem `R$` e as vezes duplicado (` 5 , 79 5 , 79R$`). O mesmo automato serve para os
tres: linhas de descricao acumulam, linhas que sao *so* numero viram precos do item
acumulado, e o bloco fecha quando a descricao seguinte comeca. O texto do OCR entra no
mesmo automato, por isso os dois caminhos compartilham a extracao.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image
from pypdf import PdfReader

# linha formada apenas por precos (com ou sem `R$`, com espacos) => preco
_SO_PRECO = re.compile(r"R\$|[\d.]+\s*,\s*\d{2}")
_NUMERO = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)\s*,\s*(\d{2})")

# ruido de layout/legal que nunca e descricao de produto
_RUIDO = re.compile(
    r"^(?:"
    r"\d{1,3}"  # numero de pagina
    r"|pre[çc]o\b.*"
    r"|limite\b.*"
    r"|\d+limite\b.*"
    r"|no app\b.*"
    r"|.*(?:por cliente|por unid)\b.*"
    r"|cart[ãa]o atacad[ãa]o.*"
    r"|carrefour.*"
    r"|sam’?s club.*"
    r"|ativada no\b.*"
    r"|esta p[áa]gina .*"
    r"|ofertas v[áa]lidas .*"
    r"|as ofertas deste box .*"
    r"|bebida alco[óo]lica .*"
    r"|anos de idade\b.*"
    r"|lei (?:estadual|federal)\b.*"
    r"|para informar o descumprimento .*"
    r"|www\..*"
    r"|ligue .*"
    r")$",
    re.IGNORECASE,
)

_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")

# rotulo de secao do encarte (ex.: MERCEARIA, HORTIFRUTI, SAUDE E BEM ESTAR, PET) e
# texto de campanha em caixa alta (SEM JUROS, NOS CARTOES): nunca e nome de produto
_SECAO = re.compile(r"^[A-ZÀ-ÜÇ][A-ZÀ-ÜÇ0-9\s\-/&.'’]{1,22}$")

# descricao vinda de OCR: precisa de uma palavra de verdade e de pouco lixo
_PALAVRA = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
_LIXO = re.compile(r"[^0-9A-Za-zÀ-ÿ\s.,%/-]")

_TEXT_CHARS_MINIMOS = 200  # abaixo disso o encarte e imagem (sem camada de texto)
_MAX_DESCRICAO = 200
_TESSDATA_LOCAL = "~/.local/share/tesseract/usr/share/tesseract-ocr"
_BINARIO_LOCAL = "~/.local/share/tesseract/usr/bin/tesseract"
_ORDEM_FONTES = ("texto", "ocr", "sem-ocr", "nenhuma")  # ordem de exibicao da fonte combinada


@dataclass
class Preco:
    """Um preco lido do encarte.

    `ordem` e a posicao do preco dentro do item; `tipo` e o papel inferido do preco
    (ex.: `varejo/atacado`, `app`, `cheio`, `clube`) quando a heuristica de
    `_classificar_tipos` consegue dizer — vazio quando e so mais um preco do item.
    """

    mercado: str
    pagina: int
    produto: str
    preco: float
    ordem: int
    tipo: str = ""


@dataclass
class Leitura:
    """Precos de um encarte e de onde eles vieram."""

    precos: list[Preco] = field(default_factory=list)
    fonte: str = "nenhuma"  # texto | ocr | sem-ocr | nenhuma

    @property
    def itens(self) -> int:
        return len({(preco.pagina, preco.produto) for preco in self.precos})


@dataclass
class Ocr:
    """Configuracao do tesseract para os encartes em imagem.

    `binario`/`tessdata` vazios: procura no PATH, na variavel TESSDATA_PREFIX e na
    instalacao local em `~/.local/share/tesseract` (o `install-deps` do Playwright nao
    instala tesseract; veja o README).
    """

    ativo: bool = True
    binario: str = ""
    tessdata: str = ""
    idioma: str = "por"
    psm: int = 12  # 12 = texto esparso: melhor recall medido nos encartes do Assai
    ld_library_path: str = ""

    @classmethod
    def from_config(cls, secao: dict) -> "Ocr":
        return cls(
            ativo=bool(secao.get("ocr", True)),
            binario=str(secao.get("ocr_bin", "") or ""),
            tessdata=str(secao.get("ocr_tessdata", "") or ""),
            idioma=str(secao.get("ocr_idioma", "por") or "por"),
            psm=int(secao.get("ocr_psm", 12) or 12),
            ld_library_path=str(secao.get("ocr_ld_library_path", "") or ""),
        )

    def caminho_binario(self) -> str | None:
        for candidato in (self.binario, shutil.which("tesseract") or "", _BINARIO_LOCAL):
            if not candidato:
                continue
            caminho = Path(candidato).expanduser()
            if caminho.exists():
                return str(caminho)
        return None

    def caminho_tessdata(self) -> str | None:
        for candidato in (self.tessdata, os.environ.get("TESSDATA_PREFIX", "")):
            if candidato and Path(candidato).expanduser().is_dir():
                return str(Path(candidato).expanduser())
        locais = sorted(Path(_TESSDATA_LOCAL).expanduser().glob("*/tessdata"))
        return str(locais[0]) if locais else None

    def ambiente(self) -> dict[str, str]:
        env = dict(os.environ)
        tessdata = self.caminho_tessdata()
        if tessdata:
            env["TESSDATA_PREFIX"] = tessdata
        if self.ld_library_path:
            caminhos = os.pathsep.join(
                str(Path(parte).expanduser()) for parte in self.ld_library_path.split(os.pathsep) if parte
            )
            anterior = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{caminhos}:{anterior}" if anterior else caminhos
        return env


def page_texts(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages]


def extract(dados: bytes, mercado: str, ocr: Ocr | None = None) -> Leitura:
    """Le os precos de um PDF ou de uma imagem. `fonte` diz de onde vieram.

    Imagem (JPEG/PNG) so tem preco via OCR; PDF pode ter camada de texto.
    """
    if _eh_imagem(dados):
        if ocr is None or not ocr.ativo:
            return Leitura([], "nenhuma")
        if ocr.caminho_binario() is None:
            return Leitura([], "sem-ocr")
        texto = _ocr_imagem(dados, ocr)
        return Leitura(_extract_page(texto, mercado, 1, limpar=True), "ocr") if texto else Leitura([], "ocr")

    textos = page_texts(dados)
    if sum(len(texto) for texto in textos) >= _TEXT_CHARS_MINIMOS:
        precos = [
            preco
            for numero, texto in enumerate(textos, start=1)
            for preco in _extract_page(texto, mercado, numero)
        ]
        return Leitura(precos, "texto")

    if ocr is None or not ocr.ativo:
        return Leitura([], "nenhuma")
    if ocr.caminho_binario() is None:
        return Leitura([], "sem-ocr")
    return Leitura(_extract_ocr(dados, mercado, ocr), "ocr")


def _eh_imagem(dados: bytes) -> bool:
    if dados[:2] == b"\xff\xd8" or dados[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    # o CDN do jornal do Examine ja devolveu WebP com URL .png
    return dados[:4] == b"RIFF" and dados[8:12] == b"WEBP"


def arquivos_brutos(data_dir: Path, dia: date, mercado: str) -> list[Path]:
    """Arquivos de `data/<dia>/raw/<mercado>-*`, na ordem em que foram baixados.

    Sao os arquivos originais: como o PDF do dia pode estar comprimido (e, no modo
    `forte`, sem camada de texto), a leitura de precos parte deles quando existem.
    """
    pasta = data_dir / dia.isoformat() / "raw"
    if not pasta.is_dir():
        return []
    arquivos = [
        caminho
        for caminho in pasta.glob(f"{mercado}-*")
        if caminho.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png")
    ]
    return sorted(arquivos, key=_indice)


def _indice(caminho: Path) -> int:
    try:
        return int(caminho.stem.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def extract_arquivos(caminhos: list[Path], mercado: str, ocr: Ocr | None = None) -> Leitura:
    """Junta a leitura de varios arquivos do mesmo mercado (um por folheto/pagina).

    A `fonte` resultante e a combinacao das fontes de cada arquivo na ordem
    `texto+ocr+sem-ocr+nenhuma` (ex.: `texto+sem-ocr` quando um folheto tinha
    camada de texto e o outro ficou sem OCR).
    """
    precos: list[Preco] = []
    fontes: set[str] = set()
    for caminho in caminhos:
        try:
            dados = caminho.read_bytes()
        except OSError:
            continue
        leitura = extract(dados, mercado, ocr)
        precos.extend(leitura.precos)
        fontes.add(leitura.fonte)
    if not fontes:
        return Leitura()
    return Leitura(precos, "+".join(fonte for fonte in _ORDEM_FONTES if fonte in fontes))


def _extract_ocr(pdf: bytes, mercado: str, ocr: Ocr) -> list[Preco]:
    precos: list[Preco] = []
    for numero, pagina in enumerate(PdfReader(BytesIO(pdf)).pages, start=1):
        for imagem in pagina.images:
            texto = _ocr_imagem(imagem.data, ocr)
            if texto:
                precos.extend(_extract_page(texto, mercado, numero, limpar=True))
    return precos


def _ocr_imagem(dados: bytes, ocr: Ocr) -> str:
    """OCR de uma imagem. Converte para escala de cinza: medido ~5x mais precos que a cor."""
    binario = ocr.caminho_binario()
    if binario is None:
        return ""
    with NamedTemporaryFile(suffix=".png", delete=False) as arquivo:
        caminho = Path(arquivo.name)
    try:
        with Image.open(BytesIO(dados)) as imagem:
            imagem.convert("L").save(caminho, "PNG")
        processo = subprocess.run(
            [binario, str(caminho), "stdout", "-l", ocr.idioma, "--psm", str(ocr.psm)],
            env=ocr.ambiente(),
            capture_output=True,
            text=True,
            timeout=180,
        )
        return processo.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[ocr] falha na imagem: {type(exc).__name__}: {exc}", file=sys.stderr)
        return ""
    finally:
        caminho.unlink(missing_ok=True)


def _extract_page(texto: str, mercado: str, pagina: int, limpar: bool = False) -> list[Preco]:
    precos: list[Preco] = []
    descricao: list[str] = []
    pendentes: list[float] = []
    pendentes_emitidos: list[Preco] = []
    emitidos = 0
    flush_pendente = False

    for bruta in texto.splitlines():
        linha = _CONTROLE.sub("", " ".join(bruta.split()))
        if not linha:
            continue

        valores = _valores(linha)
        if valores is not None:
            if descricao:
                produto = " ".join(descricao)[:_MAX_DESCRICAO]
                emitidos = _emitir(precos, mercado, pagina, produto, valores, emitidos)
                flush_pendente = False
                pendentes_emitidos = []
            else:
                # ha encarte (Atacadao) que desenha o preco antes do nome: segura o
                # preco e atribui quando a descricao aparecer
                pendentes.extend(valores)
            continue

        if _RUIDO.match(linha) or _SECAO.match(linha):
            continue
        if limpar and not _parece_nome(linha):
            continue
        if emitidos and not flush_pendente:  # descricao depois de precos => novo item
            descricao = []
            emitidos = 0
        descricao.append(linha)
        nome = " ".join(descricao)[:_MAX_DESCRICAO]
        if pendentes:
            antes = len(precos)
            emitidos = _emitir(precos, mercado, pagina, nome, pendentes, emitidos)
            pendentes_emitidos = precos[antes:]
            pendentes = []
            flush_pendente = True
        elif flush_pendente and pendentes_emitidos:  # o nome do item tem mais linhas
            for preco in pendentes_emitidos:
                preco.produto = nome

    if pendentes:  # a pagina acabou sem nenhuma descricao para esses precos
        _emitir(precos, mercado, pagina, "", pendentes, emitidos)

    _classificar_tipos(precos, mercado)
    return precos


def _emitir(
    precos: list[Preco], mercado: str, pagina: int, produto: str, valores: list[float], emitidos: int
) -> int:
    for valor in valores:
        emitidos += 1
        precos.append(Preco(mercado, pagina, produto, valor, emitidos))
    return emitidos


def _classificar_tipos(precos: list[Preco], mercado: str) -> None:
    """Preenche `tipo` nos blocos em que da para inferir o papel de cada preco.

    O texto extraido nao tem os rotulos legiveis do encarte, mas os encartes
    publicam os precos do item sempre do maior para o menor, com papeis fixos por
    mercado (verificado nos encartes de 15/10/2026; ver README):

    - Atacadao: `varejo/atacado`, `app`, `app/cartao` (o preco do app com cartao e o
      menor; bloco de 2 fica `varejo/atacado` + `app`; bloco de 1 fica sem tipo).
    - Savegnago e Covabra: `cheio` e `clube` (o preco do clube/desconto e o menor).

    Bloco com tamanho inesperado (ex.: itens fundidos pela ordem de leitura do PDF)
    fica todo sem tipo, para nao rotular preco errado.
    """
    if mercado == "atacadao":
        papeis = ("varejo/atacado", "app", "app/cartao")
    elif mercado in ("savegnago", "covabra"):
        papeis = ("cheio", "clube")
    else:
        return

    for bloco in _blocos(precos):
        if not 2 <= len(bloco) <= len(papeis):
            continue
        ordenados = sorted(bloco, key=lambda preco: preco.preco, reverse=True)
        for posicao, preco in enumerate(ordenados[: len(papeis)]):
            preco.tipo = papeis[posicao]


def _blocos(precos: list[Preco]):
    """Runs consecutivos de `(pagina, produto)` — um item do encarte."""
    bloco: list[Preco] = []
    for preco in precos:
        chave = (preco.pagina, preco.produto)
        if bloco and chave != (bloco[-1].pagina, bloco[-1].produto):
            yield bloco
            bloco = []
        bloco.append(preco)
    if bloco:
        yield bloco


def _parece_nome(linha: str) -> bool:
    """Descricao utilizavel vinda de OCR: tem palavra de verdade e pouco lixo.

    O OCR de encarte artístico devolve muito traco solto (`— — | E te LUCRAR MAIS!`);
    isso nao e nome de produto e so atrapalharia a planilha.
    """
    if not _PALAVRA.search(linha):
        return False
    return len(_LIXO.findall(linha)) <= len(linha) * 0.2


def _valores(linha: str) -> list[float] | None:
    """Precos da linha, ou None se a linha nao for so numeros de preco."""
    if "R$" not in linha and "," not in linha:
        return None
    if _SO_PRECO.sub(" ", linha).strip():
        return None
    valores = [
        float(f"{inteiro.replace('.', '')}.{centavos}") for inteiro, centavos in _NUMERO.findall(linha)
    ]
    # Savegnago repete o mesmo preco na linha (`5 , 79 5 , 79R$`)
    unicos: list[float] = []
    for valor in valores:
        if not unicos or unicos[-1] != valor:
            unicos.append(valor)
    return unicos or None


def csv_text(precos: list[Preco]) -> str:
    out = StringIO()
    escritor = csv.writer(out, delimiter=";", lineterminator="\n")
    escritor.writerow(["mercado", "pagina", "produto", "preco", "ordem", "tipo"])
    for preco in precos:
        escritor.writerow(
            [preco.mercado, preco.pagina, preco.produto, f"{preco.preco:.2f}", preco.ordem, preco.tipo]
        )
    return out.getvalue()


def write(precos: list[Preco], data_dir: Path, dia: date, mercado: str) -> tuple[Path, Path]:
    """Grava `precos/<mercado>.json` e `.csv`; devolve os dois caminhos.

    O CSV sai com BOM (`utf-8-sig`) para abrir direto no Excel pt-BR; o JSON fica
    em UTF-8 puro.
    """
    folder = data_dir / dia.isoformat() / "precos"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"{mercado}.json"
    csv_path = folder / f"{mercado}.csv"
    json_path.write_text(
        json.dumps([asdict(preco) for preco in precos], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    csv_path.write_text(csv_text(precos), encoding="utf-8-sig")
    return json_path, csv_path
