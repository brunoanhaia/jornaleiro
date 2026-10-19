"""Compressao dos PDFs antes de gravar/enviar.

O peso dos encartes esta nos JPEGs embutidos. A compressao reencoda essas imagens com
qualidade menor, largura maxima menor e, quando a imagem tem mascara suave (`/SMask`),
**achata** a mascara no fundo branco (virando RGB) e joga a mascara fora - e o que os
compressores comerciais fazem, e o que permite reduzir de verdade as paginas CMYK do
Covabra e do Savegnago, que sao a maior parte do arquivo.

Medido nos encartes de 15/10/2026, ja com todas as paginas em A4:

    modo `padrao` (reencoda imagem por imagem, achata mascara, qualidade 60, largura 1400)
        assai      8,92 MB -> 1,62 MB  (-82%)
        atacadao  20,25 MB -> 13,39 MB (-34%)
        covabra    4,03 MB -> 2,04 MB  (-49%)
        savegnago  3,56 MB -> 1,72 MB  (-52%)
        examine    0,56 MB -> 0,25 MB  (-54%)

    modo `forte` (rasteriza cada pagina a 150 dpi, qualidade 60 - o que o `jornaleiro run` usa)
        assai      8,92 MB -> 1,68 MB  (-81%)
        atacadao  20,25 MB ->  3,74 MB (-82%)
        covabra    4,03 MB ->  0,81 MB (-80%)
        savegnago  3,56 MB ->  0,79 MB (-78%)
        examine    0,56 MB ->  0,22 MB (-61%)

No modo `forte` a camada de texto se perde (a pagina vira imagem) - por isso a leitura de
precos parte dos arquivos brutos em `data/<dia>/raw/`, que nunca passam por compressao.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import img2pdf
from PIL import Image
from pikepdf import Name, ObjectStreamMode, Pdf, PdfImage

A4 = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))  # retrato, em pontos
CORES_SEGURAS = ("/DeviceRGB", "/DeviceGray", "/DeviceCMYK")
FILTROS = (Name.DCTDecode, Name.FlateDecode)
GANHO_MINIMO = 0.9  # so troca se o novo JPEG for pelo menos 10% menor


@dataclass
class Compressao:
    qualidade: int = 60
    largura_max: int = 1400
    achatar_mascara: bool = True
    # `forte`: cada pagina vira uma imagem (perde a camada de texto; os precos sao lidos
    # dos arquivos brutos em data/<dia>/raw/, que nao passam por compressao)
    rasterizar: bool = False
    dpi: int = 110
    pagina: tuple[float, float] | None = A4


@dataclass
class Resultado:
    antes: int
    depois: int
    imagens: int
    puladas: int
    achatadas: int = 0

    @property
    def economia(self) -> float:
        return 1 - self.depois / self.antes if self.antes else 0.0


def compress(pdf_bytes: bytes, opcoes: Compressao) -> tuple[bytes, Resultado]:
    """Devolve (bytes comprimidos, estatisticas). Nunca cresce o arquivo por imagem."""
    if opcoes.rasterizar:
        return _rasterizar(pdf_bytes, opcoes)

    pdf = Pdf.open(io.BytesIO(pdf_bytes))
    imagens = puladas = achatadas = 0

    for page in pdf.pages:
        xobjetos = page.get("/Resources", {}).get("/XObject", {})
        for chave in list(xobjetos.keys()):
            objeto = xobjetos[chave]
            novo, achatou = _reencodar(pdf, objeto, opcoes)
            if novo is None:
                puladas += 1
                continue
            xobjetos[chave] = novo
            imagens += 1
            achatadas += 1 if achatou else 0

    saida = io.BytesIO()
    pdf.save(saida, compress_streams=True, object_stream_mode=ObjectStreamMode.generate)
    return saida.getvalue(), Resultado(len(pdf_bytes), saida.tell(), imagens, puladas, achatadas)


def _rasterizar(pdf_bytes: bytes, opcoes: Compressao) -> tuple[bytes, Resultado]:
    """Compressao forte: cada pagina vira um JPEG (A4), como fazem os compressores comerciais."""
    import pypdfium2 as pdfium

    documento = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    paginas: list[bytes] = []
    try:
        for pagina in documento:
            imagem = pagina.render(scale=opcoes.dpi / 72).to_pil().convert("RGB")
            paginas.append(_jpeg_em_a4(imagem, opcoes))
    finally:
        documento.close()

    layout = img2pdf.get_layout_fun(opcoes.pagina, fit=img2pdf.FitMode.into)
    comprimido = img2pdf.convert(paginas, layout_fun=layout)
    return comprimido, Resultado(len(pdf_bytes), len(comprimido), len(paginas), 0, len(paginas))


def _jpeg_em_a4(imagem: Image.Image, opcoes: Compressao) -> bytes:
    if not opcoes.pagina:
        buffer = io.BytesIO()
        imagem.save(buffer, "JPEG", quality=opcoes.qualidade, optimize=True, progressive=True)
        return buffer.getvalue()

    alvo = _pixels(opcoes.pagina, opcoes.dpi)
    copia = imagem.copy()
    copia.thumbnail(alvo, Image.LANCZOS)
    pagina = Image.new("RGB", alvo, "white")
    pagina.paste(copia, ((alvo[0] - copia.width) // 2, (alvo[1] - copia.height) // 2))
    buffer = io.BytesIO()
    pagina.save(buffer, "JPEG", quality=opcoes.qualidade, optimize=True, progressive=True)
    return buffer.getvalue()


def _pixels(pagina: tuple[float, float], dpi: int) -> tuple[int, int]:
    return (round(pagina[0] / 72 * dpi), round(pagina[1] / 72 * dpi))


def _reencodar(pdf: Pdf, objeto, opcoes: Compressao):
    """(novo stream, achatou mascara) ou (None, False) se a imagem deve ficar como esta."""
    if not _reencodavel(objeto):
        return None, False

    cor = str(objeto.get("/ColorSpace"))
    tem_mascara = "/SMask" in objeto
    achatou = bool(tem_mascara and opcoes.achatar_mascara)

    try:
        imagem = PdfImage(objeto).as_pil_image()
        if achatou:
            mascara = PdfImage(objeto.SMask).as_pil_image().convert("L")
            if mascara.size != imagem.size:
                mascara = mascara.resize(imagem.size, Image.LANCZOS)
            fundo = Image.new("RGB", imagem.size, "white")
            imagem = Image.composite(imagem.convert("RGB"), fundo, mascara)
    except Exception:  # noqa: BLE001 - imagem que o pikepdf/Pillow nao decodifica
        return None, False

    if cor == "/DeviceCMYK" and imagem.mode == "CMYK" and not achatou:
        pass  # mantem CMYK (sem achar, o que aparece na pagina depende dessas tintas)
    elif imagem.mode not in ("RGB", "L") and not achatou:
        imagem = imagem.convert("CMYK" if cor == "/DeviceCMYK" else "L")

    # com mascara preservada nao da para reamostrar so a base: a mascara sairia do lugar
    largura_max = opcoes.largura_max if (achatou or not tem_mascara) else 0
    if largura_max and imagem.width > largura_max:
        altura = max(1, round(imagem.height * largura_max / imagem.width))
        imagem = imagem.resize((largura_max, altura), Image.LANCZOS)

    buffer = io.BytesIO()
    try:
        imagem.save(buffer, "JPEG", quality=opcoes.qualidade, optimize=True, progressive=True)
    except OSError:  # modo que o Pillow nao salva como JPEG
        return None, False

    novo = buffer.getvalue()
    if len(novo) >= len(objeto.read_raw_bytes()) * GANHO_MINIMO:
        return None, False

    stream = pdf.make_stream(novo)
    stream.Type = Name.XObject
    stream.Subtype = Name.Image
    stream.Width = imagem.width
    stream.Height = imagem.height
    stream.ColorSpace = Name.DeviceRGB if achatou else objeto.get("/ColorSpace")
    stream.BitsPerComponent = 8
    stream.Filter = Name.DCTDecode
    return stream, achatou


def _reencodavel(objeto) -> bool:
    if objeto.get("/Subtype") != Name.Image:
        return False
    if objeto.get("/Filter") not in FILTROS:
        return False
    if objeto.get("/BitsPerComponent") != 8 or "/Decode" in objeto:
        return False
    return str(objeto.get("/ColorSpace")) in CORES_SEGURAS
