"""CLI: coleta, compila, envia e le os precos dos encartes de Rio Claro/SP.

Subcomandos:
    jornais run            coleta, compila um PDF por mercado e envia pelo Telegram
    jornais precos         le os precos dos PDFs ja baixados em data/<dia>/
    jornais site-precos    le o catalogo do site do Examine (GraphQL)
    jornais render <url>   imprime o texto renderizado (debug do renderizador)
    jornais examine-probe  mostra a cadeia de descoberta do encarte do Examine
    jornais limpar         remove coletas antigas de data/ (retencao)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv

from . import comprimir, compose, http, notify, precos, render, site
from .markets import ORDER, REGISTRY, examine, safe_fetch
from .model import Context, MarketCfg, MarketResult, SP, describe_error
from .state import State

DEFAULT_CONFIG = "config.toml"


@dataclass
class Row:
    """O que a coleta produziu para um mercado (vai para o resumo e para o log)."""

    result: MarketResult
    count: int = 0
    unit: str = "pag"
    path: Path | None = None
    csv: Path | None = None
    antes: int = 0
    depois: int = 0
    itens: int = 0
    precos: int = 0
    fonte: str = "nenhuma"
    erro_precos: str | None = None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:  # pragma: no cover - interrupcao manual
        return 130


class _Espelho(io.TextIOBase):
    """Escreve no destino original (terminal) e no arquivo de log ao mesmo tempo."""

    def __init__(self, destino: io.TextIOBase, arquivo: io.TextIOBase) -> None:
        self._destino = destino
        self._arquivo = arquivo

    def write(self, texto: str) -> int:
        self._destino.write(texto)
        self._arquivo.write(texto)
        return len(texto)

    def flush(self) -> None:
        self._destino.flush()
        self._arquivo.flush()

    @property
    def encoding(self) -> str:
        return getattr(self._destino, "encoding", "utf-8")

    def isatty(self) -> bool:
        return False


class _Transcricao:
    """Espelha stdout/stderr em `data/<dia>/run.log` durante a execucao."""

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self._arquivo: io.TextIOBase | None = None
        self._originais: tuple[io.TextIOBase, io.TextIOBase] | None = None

    def __enter__(self) -> _Transcricao:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._arquivo = self.caminho.open("a", encoding="utf-8")
        self._arquivo.write(f"\n==== execucao em {datetime.now(SP):%d/%m/%Y %H:%M:%S} ====\n")
        self._originais = (sys.stdout, sys.stderr)
        sys.stdout = _Espelho(sys.stdout, self._arquivo)
        sys.stderr = _Espelho(sys.stderr, self._arquivo)
        return self

    def __exit__(self, *_erro: object) -> None:
        if self._originais is not None:
            sys.stdout, sys.stderr = self._originais
            self._originais = None
        if self._arquivo is not None:
            self._arquivo.flush()
            self._arquivo.close()
            self._arquivo = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jornais", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="coleta, compila e envia os encartes")
    run.add_argument("--only", help="mercados separados por virgula (ex.: assai,covabra)")
    run.add_argument("--renderer", choices=render.MODES)
    run.add_argument("--no-send", action="store_true", help="apenas gera os PDFs")
    run.add_argument("--sem-comprimir", action="store_true", help="nao comprime os PDFs")
    run.add_argument("--sem-ocr", action="store_true", help="nao roda OCR nos encartes em imagem")
    run.add_argument("--sem-precos", action="store_true", help="nao le nem envia precos (so os jornais)")
    run.add_argument("--data-dir")
    run.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNAIS_CONFIG)")
    run.set_defaults(handler=cmd_run)

    precos_cmd = sub.add_parser("precos", help="le os precos dos PDFs ja baixados")
    precos_cmd.add_argument("--dia", help="dia da coleta (AAAA-MM-DD, padrao: hoje)")
    precos_cmd.add_argument("--only", help="mercados separados por virgula")
    precos_cmd.add_argument("--sem-ocr", action="store_true", help="nao roda OCR nos encartes em imagem")
    precos_cmd.add_argument("--data-dir")
    precos_cmd.add_argument("--json", action="store_true", help="imprime os precos no stdout")
    precos_cmd.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNAIS_CONFIG)")
    precos_cmd.set_defaults(handler=cmd_precos)

    catalogo = sub.add_parser("site-precos", help="le os precos do site do Examine (GraphQL)")
    catalogo.add_argument("--dia", help="dia da coleta (AAAA-MM-DD, padrao: hoje)")
    catalogo.add_argument("--max-categorias", type=int, help="limita quantas categorias varrer")
    catalogo.add_argument("--data-dir")
    catalogo.add_argument("--json", action="store_true", help="imprime os produtos no stdout")
    catalogo.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNAIS_CONFIG)")
    catalogo.set_defaults(handler=cmd_site_precos)

    show = sub.add_parser("render", help="imprime o texto renderizado de uma URL")
    show.add_argument("url")
    show.add_argument("--renderer", choices=render.MODES)
    show.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNAIS_CONFIG)")
    show.set_defaults(handler=cmd_render)

    probe = sub.add_parser("examine-probe", help="debug da descoberta do post do Examine")
    probe.add_argument("--renderer", choices=render.MODES)
    probe.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNAIS_CONFIG)")
    probe.set_defaults(handler=cmd_examine_probe)

    limpar = sub.add_parser("limpar", help="remove coletas antigas de data/ (retencao)")
    limpar.add_argument("--dias", type=int, default=30, help="manter as coletas dos ultimos N dias (padrao: 30)")
    limpar.add_argument("--dry-run", action="store_true", help="apenas mostra o que seria removido")
    limpar.add_argument("--data-dir")
    limpar.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNAIS_CONFIG)")
    limpar.set_defaults(handler=cmd_limpar)

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    load_dotenv()
    config_path = localizar_config(args.config)
    config = load_config(config_path)
    data_dir = resolver_data_dir(args, config, config_path)

    keys = select_markets(config, args.only)
    if keys is None:
        return 2

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not args.no_send and not (token and chat_id):
        print("defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    lendo_precos = not args.sem_precos and config_ler_precos(config)
    compressao = None if args.sem_comprimir else config_compressao(config)
    ocr = None if (args.sem_ocr or not lendo_precos) else config_ocr(config)
    today = datetime.now(SP).date()

    # tudo o que sai no terminal tambem fica em data/<dia>/run.log
    with _Transcricao(data_dir / today.isoformat() / "run.log"):
        renderer = render.build_renderer(args.renderer or config["renderer"])
        state = State.load(data_dir / "state.json")
        ctx = Context(renderer=renderer, today_sp=today, state=state)

        rows: list[Row] = []
        try:
            for key in keys:
                result = safe_fetch(REGISTRY[key], ctx, config["markets"][key])
                cfg = config["markets"][key]
                # o Examine tem preco estruturado no site: nao gasta OCR no encarte em imagem
                ocr_mercado = None if (key == "examine" and cfg.get("precos_site", False)) else ocr
                try:
                    row = publish(
                        result,
                        data_dir,
                        today,
                        compressao=compressao,
                        ocr=ocr_mercado,
                        ler_precos=lendo_precos,
                    )
                except Exception as exc:  # noqa: BLE001 - um mercado nao aborta os demais
                    result.status = "failed"
                    result.error = result.error or describe_error(exc)
                    row = Row(result=result)
                if lendo_precos and key == "examine" and cfg.get("precos_site", False):
                    try:
                        ler_precos_site(row, cfg, data_dir, today)
                    except Exception as exc:  # noqa: BLE001 - o PDF do jornal ainda vai
                        row.erro_precos = describe_error(exc)
                        print(f"[examine] catalogo do site falhou: {row.erro_precos}", file=sys.stderr)
                rows.append(row)
                print(f"{key}: {describe(row)}", file=sys.stdout if row.path else sys.stderr)
        finally:
            renderer.close()
            http.close()

        state.save()

        message = summary_message(today, rows)
        print(message)

        if not args.no_send:
            telegram = notify.Telegram(token, chat_id)
            telegram.send_message(message)
            notify.send_report(
                telegram,
                documentos(rows, enviar_precos=lendo_precos and config_enviar_precos(config)),
            )
        return exit_code(rows)


def cmd_precos(args: argparse.Namespace) -> int:
    """Le os precos dos PDFs que ja estao em data/<dia>/ (sem baixar nada)."""
    load_dotenv()
    config_path = localizar_config(args.config)
    config = load_config(config_path)
    data_dir = resolver_data_dir(args, config, config_path)
    keys = select_markets(config, args.only)
    if keys is None:
        return 2
    dia = date.fromisoformat(args.dia) if args.dia else datetime.now(SP).date()
    ocr = None if args.sem_ocr else config_ocr(config)

    total = 0
    vazios: list[tuple[str, str]] = []
    for key in keys:
        pdf = data_dir / dia.isoformat() / f"{key}.pdf"
        if not pdf.exists():
            print(f"{key}: sem PDF em {pdf} (rode `jornais run`)", file=sys.stderr)
            continue
        brutos = precos.arquivos_brutos(data_dir, dia, key)
        if brutos:
            leitura = precos.extract_arquivos(brutos, key, ocr)
        else:
            leitura = precos.extract(pdf.read_bytes(), key, ocr)
        if not leitura.precos:
            vazios.append((key, leitura.fonte))
            continue
        _, csv_path = precos.write(leitura.precos, data_dir, dia, key)
        total += len(leitura.precos)
        print(
            f"{key}: {len(leitura.precos)} precos ({leitura.itens} itens)"
            f"{_rotulo_fonte(leitura.fonte)} -> {csv_path}"
        )
        if args.json:
            for preco in leitura.precos:
                print(json.dumps(asdict(preco), ensure_ascii=False))

    for key, fonte in vazios:
        print(f"{key}: {_motivo_vazio(fonte)}", file=sys.stderr)
    return 0 if total else 1


def ler_precos_site(row: Row, cfg: MarketCfg, data_dir: Path, today: date) -> None:
    """Le o catalogo do site do Examine e usa isso como leitura de precos do mercado."""
    cliente = site_do_config(cfg)
    produtos = cliente.catalogo(
        max_categorias=int(cfg.get("site_categorias_max", 0) or 0),
        ao_progredir=lambda nome, quantos, total: print(f"  site {nome}: {quantos} produtos ({total})"),
    )
    _, row.csv = site.write(produtos, data_dir, today, "examine")
    row.itens, row.precos, row.fonte = len(produtos), len(produtos), "site"


def site_do_config(cfg: MarketCfg) -> site.Site:
    url = str(cfg.get("site_url", "") or "")
    return site.Site(
        str(cfg.get("site_graphql", site.GRAPHQL_PADRAO)),
        origin=url or "https://superexaminerc.crescevendas.com",
    )


def cmd_site_precos(args: argparse.Namespace) -> int:
    """Le os precos do catalogo do site do Examine (GraphQL), sem OCR."""
    load_dotenv()
    config_path = localizar_config(args.config)
    config = load_config(config_path)
    data_dir = resolver_data_dir(args, config, config_path)
    cfg = config["markets"]["examine"]
    dia = date.fromisoformat(args.dia) if args.dia else datetime.now(SP).date()
    max_categorias = args.max_categorias if args.max_categorias is not None else int(
        cfg.get("site_categorias_max", 0) or 0
    )

    produtos = site_do_config(cfg).catalogo(
        max_categorias=max_categorias,
        ao_progredir=lambda nome, quantos, total: print(f"{nome}: {quantos} produtos ({total} no total)"),
    )
    if not produtos:
        print("nenhum produto retornado pelo site", file=sys.stderr)
        return 1
    _, csv_path = site.write(produtos, data_dir, dia, "examine")
    precos_vistos = len({produto.id for produto in produtos})
    print(f"examine: {len(produtos)} produtos ({precos_vistos} ids unicos) -> {csv_path}")
    if args.json:
        for produto in produtos:
            print(json.dumps(asdict(produto), ensure_ascii=False))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    load_dotenv()
    renderer = render.build_renderer(args.renderer or "auto")
    try:
        text = renderer.get_text(args.url)
    finally:
        renderer.close()
        http.close()
    print(text[:2000])
    return 0


def cmd_examine_probe(args: argparse.Namespace) -> int:
    from PIL import Image

    load_dotenv()
    config_path = localizar_config(args.config)
    config = load_config(config_path)
    cfg = config["markets"]["examine"]
    renderer = render.build_renderer(args.renderer or config["renderer"])
    state = State.load(resolver_data_dir(args, config, config_path) / "state.json")
    ctx = Context(renderer=renderer, today_sp=datetime.now(SP).date(), state=state)

    try:
        seed, candidates = examine.discover(ctx, cfg)
        print(f"semente: {seed}")
        print(f"candidatos ({len(candidates)}): {', '.join(candidates) or '-'}")

        seed_code = examine.shortcode(seed)
        codes = [seed_code] if seed_code else []
        codes += [code for code in candidates if code not in codes]

        posts: list[tuple[str, str | None, date | None, bool, str]] = []
        for code in codes:
            text = renderer.get_text(examine.POST_URL.format(code=code))
            texto_legenda = examine.extract_caption(text)
            posted = examine.post_date(texto_legenda, text)
            is_encarte = bool(texto_legenda and examine.is_encarte(texto_legenda, cfg))
            posts.append((code, texto_legenda, posted, is_encarte, text))
            print(f"post {code}: {'encarte' if is_encarte else 'ignorado'} data={posted}")

        matches = [post for post in posts if post[3]]
        if not matches:
            print("nenhum post de encarte entre a semente e os candidatos")
            return 1

        chosen = max(matches, key=lambda post: post[2] or date.min)
        print(f"escolhido: {examine.POST_URL.format(code=chosen[0])}")
        print(f"validade: {examine.validity_of(chosen[1] or '')}")
        print(f"legenda: {chosen[1]}")

        urls = examine.image_urls(chosen[4])
        if not urls:
            fallback = examine.og_image(chosen[4])
            urls = [fallback] if fallback else []
            print("aviso: sem imagem em tamanho real; usando og:image")
        for url in urls:
            content = http.get_bytes(url, headers=examine.IMAGE_HEADERS)
            width, height = Image.open(BytesIO(content)).size
            print(f"imagem: {width}x{height} ({len(content)} bytes) {url}")
    finally:
        renderer.close()
        http.close()
    return 0


def cmd_limpar(args: argparse.Namespace) -> int:
    """Remove coletas antigas de `data/`, mantendo as dos ultimos `--dias`."""
    load_dotenv()
    config_path = localizar_config(args.config)
    config = load_config(config_path)
    data_dir = resolver_data_dir(args, config, config_path)
    if args.dias < 0:
        print("--dias precisa ser >= 0", file=sys.stderr)
        return 2

    limite = datetime.now(SP).date() - timedelta(days=args.dias)
    alvos: list[tuple[Path, int]] = []
    if data_dir.is_dir():
        for pasta in sorted(data_dir.iterdir()):
            if not pasta.is_dir():
                continue
            try:
                dia = date.fromisoformat(pasta.name)
            except ValueError:
                continue  # pasta que nao e de coleta (ex.: raw/ de algo solto)
            if dia < limite:
                alvos.append((pasta, _tamanho(pasta)))

    total = sum(tamanho for _, tamanho in alvos)
    for pasta, tamanho in alvos:
        if args.dry_run:
            print(f"seria removida: {pasta} ({tamanho / 1048576:.1f} MB)")
        else:
            shutil.rmtree(pasta)
            print(f"removida: {pasta} ({tamanho / 1048576:.1f} MB)")
    acao = "seriam removidas" if args.dry_run else "removidas"
    print(f"{acao} {len(alvos)} coleta(s), {total / 1048576:.1f} MB (retendo {args.dias} dia(s))")
    return 0


def _tamanho(pasta: Path) -> int:
    return sum(arquivo.stat().st_size for arquivo in pasta.rglob("*") if arquivo.is_file())


def publish(
    result: MarketResult,
    data_dir: Path,
    today: date,
    *,
    compressao: comprimir.Compressao | None = None,
    ocr: precos.Ocr | None = None,
    ler_precos: bool = True,
) -> Row:
    """Grava o PDF do mercado (comprimido) e, se pedido, a leitura de precos em CSV/JSON."""
    row = Row(result=result)
    if result.status != "ok" or not result.assets:
        return row

    path, pdf, estatisticas = compose.write_result(result, data_dir, today, compressao)
    row.path = path
    row.unit, row.count = measure(result, compose.page_count(pdf))
    if estatisticas is not None:
        row.antes, row.depois = estatisticas.antes, estatisticas.depois

    if not ler_precos:
        row.fonte = "desligado"
        return row

    # leitura a partir dos brutos: o PDF do dia pode estar comprimido (modo `forte`
    # rasteriza as paginas, o que apagaria a camada de texto)
    try:
        leitura = precos.extract_arquivos(
            precos.arquivos_brutos(data_dir, today, result.key), result.key, ocr
        )
    except Exception as exc:  # noqa: BLE001 - o PDF ja esta gravado; so a contagem falhou
        row.fonte = "erro"
        row.erro_precos = describe_error(exc)
        print(f"[{result.key}] leitura de precos falhou: {row.erro_precos}", file=sys.stderr)
        return row

    row.itens, row.precos, row.fonte = leitura.itens, len(leitura.precos), leitura.fonte
    if leitura.precos:
        _, row.csv = precos.write(leitura.precos, data_dir, today, result.key)
    return row


def documentos(rows: list[Row], *, enviar_precos: bool = True) -> list[tuple[str, Path, str]]:
    """Documentos na ordem de envio: PDF do mercado e, logo depois, a leitura de precos."""
    itens: list[tuple[str, Path, str]] = []
    for row in rows:
        if row.path is None:
            continue
        itens.append((row.result.label, row.path, caption(row)))
        if enviar_precos and row.csv is not None:
            itens.append((f"{row.result.label} (precos)", row.csv, caption_precos(row)))
    return itens


def caption_precos(row: Row) -> str:
    return f"{row.result.label} - {row.itens} itens/{row.precos} precos{_rotulo_fonte(row.fonte)}"


def measure(result: MarketResult, pages: int) -> tuple[str, int]:
    """Unidade do resumo: varios PDFs sao folhetos; o resto conta paginas do PDF."""
    if len(result.assets) > 1 and all(asset.kind == "pdf" for asset in result.assets):
        return "folhetos", len(result.assets)
    return ("pag" if pages == 1 else "pags"), pages


def describe(row: Row) -> str:
    """Linha de log de um mercado."""
    if row.path is None:
        return f"falha: {row.result.error}"
    partes = [f"{row.count} {row.unit} -> {row.path}"]
    if row.antes and row.depois:
        partes.append(
            f"pdf {row.antes / 1048576:.2f} MB -> {row.depois / 1048576:.2f} MB "
            f"(-{100 * (1 - row.depois / row.antes):.0f}%)"
        )
    partes.append(_precos_texto(row))
    return " | ".join(part for part in partes if part)


def summary_message(today: date, rows: list[Row]) -> str:
    lines = [f"Encartes Rio Claro - {today:%d/%m/%Y}"]
    failures: list[str] = []
    for row in rows:
        if row.path is None:
            lines.append(f"{row.result.label} - falha: {row.result.error}")
            failures.append(row.result.label)
            continue
        detail = row.result.validity or row.result.note
        suffix = f" - {detail}" if detail else ""
        precos_texto = _precos_texto(row)
        extra = f" | {precos_texto}" if precos_texto else ""
        lines.append(f"{row.result.label} - {row.count} {row.unit}{suffix}{extra}")
    lines.append("Falhas: " + (", ".join(failures) if failures else "nenhuma"))
    return "\n".join(lines)


def _precos_texto(row: Row) -> str:
    if row.erro_precos:
        return f"precos: falha ({row.erro_precos})"
    if row.precos:
        if row.fonte == "site":
            return f"{row.precos} produtos (site)"
        return f"{row.itens} itens/{row.precos} precos{_rotulo_fonte(row.fonte)}"
    return _motivo_vazio(row.fonte) if row.path is not None else ""


def _rotulo_fonte(fonte: str) -> str:
    """Marcador curto da origem dos precos ('' quando e so a camada de texto)."""
    partes = set(fonte.split("+"))
    if "ocr" in partes:
        return " (texto+OCR)" if "texto" in partes else " (OCR)"
    if "sem-ocr" in partes and "texto" in partes:
        return " (OCR indisponivel em parte)"
    return ""


_SEM_PRECOS = {
    "texto": "sem precos na camada de texto",
    "ocr": "OCR nao leu nenhum preco",
    "sem-ocr": "precos: OCR indisponivel (tesseract nao encontrado)",
    "nenhuma": "precos: encarte em imagem e OCR desligado",
    "erro": "precos: falha na leitura",
    "desligado": "",
}


def _motivo_vazio(fonte: str) -> str:
    if fonte in _SEM_PRECOS:
        return _SEM_PRECOS[fonte]
    partes = set(fonte.split("+"))
    if "sem-ocr" in partes:
        return "precos: OCR indisponivel em parte dos arquivos (tesseract nao encontrado)"
    if "nenhuma" in partes:
        return "precos: encarte em imagem e OCR desligado"
    return "sem precos"


def caption(row: Row) -> str:
    detail = row.result.validity or row.result.note or "sem validade"
    return f"{row.result.label} - {detail} - {row.count} {row.unit}"


def exit_code(rows: list[Row]) -> int:
    published = [row for row in rows if row.path is not None]
    if not published:
        return 1
    if all(row.result.status == "failed" for row in rows):
        return 1
    return 0


def localizar_config(explicito: str | None) -> Path:
    """Acha o config.toml: `--config` > `JORNAIS_CONFIG` > pasta atual > raiz do repo."""
    if explicito:
        return Path(explicito)
    do_env = os.environ.get("JORNAIS_CONFIG", "").strip()
    if do_env:
        return Path(do_env)
    aqui = Path(DEFAULT_CONFIG)
    raiz = Path(__file__).resolve().parents[2]  # src/jornais/cli.py -> raiz do repositorio
    if not aqui.exists() and (raiz / DEFAULT_CONFIG).exists():
        return raiz / DEFAULT_CONFIG
    return aqui


def resolver_data_dir(args: argparse.Namespace, config: dict, config_path: Path) -> Path:
    """`--data-dir` vence; caminho relativo do config.toml fica ao lado dele."""
    data_dir = Path(getattr(args, "data_dir", None) or config["data_dir"])
    if not data_dir.is_absolute():
        data_dir = config_path.parent / data_dir
    return data_dir


def load_config(path: Path) -> dict:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    config.setdefault("renderer", "auto")
    config.setdefault("data_dir", "data")
    config["markets"] = {
        key: MarketCfg(value) for key, value in (config.get("markets") or {}).items()
    }
    return config


def config_compressao(config: dict) -> comprimir.Compressao | None:
    secao = config.get("comprimir") or {}
    if not secao.get("enabled", True):
        return None
    modo = str(secao.get("modo", "forte") or "forte").lower()
    return comprimir.Compressao(
        qualidade=int(secao.get("qualidade", 60)),
        largura_max=int(secao.get("largura_max", 1400)),
        achatar_mascara=bool(secao.get("achatar_mascara", True)),
        rasterizar=modo == "forte",
        dpi=int(secao.get("dpi", 150)),
    )


def config_ocr(config: dict) -> precos.Ocr | None:
    ocr = precos.Ocr.from_config(config.get("precos") or {})
    return ocr if ocr.ativo else None


def config_ler_precos(config: dict) -> bool:
    """Se o `run` le os precos (chave `ler` de `[precos]`; `--sem-precos` vence)."""
    return bool((config.get("precos") or {}).get("ler", True))


def config_enviar_precos(config: dict) -> bool:
    """Se os CSVs de precos vao junto dos PDFs (chave `enviar` de `[precos]`)."""
    return bool((config.get("precos") or {}).get("enviar", True))


def select_markets(config: dict, only: str | None) -> list[str] | None:
    markets = config["markets"]
    if only:
        wanted = {key.strip() for key in only.split(",") if key.strip()}
        unknown = sorted(key for key in wanted if key not in markets)
        if unknown:
            print(
                f"mercado desconhecido: {', '.join(unknown)} (use: {', '.join(ORDER)})",
                file=sys.stderr,
            )
            return None
        return [key for key in ORDER if key in wanted]

    keys = [key for key in ORDER if markets.get(key, {}).get("enabled", False)]
    if not keys:
        print("nenhum mercado habilitado no config.toml", file=sys.stderr)
    return keys


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
