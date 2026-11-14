"""CLI: coleta, compila e envia os encartes de Rio Claro/SP pelo Telegram.

Subcomandos:
    jornaleiro run            coleta, compila um PDF por mercado e envia pelo Telegram
    jornaleiro render <url>   imprime o texto renderizado (debug do renderizador)
    jornaleiro examine-probe  mostra a cadeia de descoberta do encarte do Examine
    jornaleiro limpar         remove coletas antigas de data/ (retencao)
    jornaleiro serve          agenda interna: roda a coleta nos horarios configurados
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shutil
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Self

from dotenv import load_dotenv

from . import agenda, compose, comprimir, http, notify, render
from .markets import ORDER, REGISTRY, examine, safe_fetch
from .model import SP, Asset, Context, MarketCfg, MarketResult, describe_error
from .state import State

DEFAULT_CONFIG = "config.toml"


@dataclass
class Row:
    """O que a coleta produziu para um mercado (vai para o resumo e para o log)."""

    result: MarketResult
    count: int = 0
    unit: str = "pag"
    path: Path | None = None
    antes: int = 0
    depois: int = 0
    sha: str = ""
    aviso: str = ""
    pular_envio: bool = False


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

    def __enter__(self) -> Self:
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
    parser = argparse.ArgumentParser(prog="jornaleiro", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="coleta, compila e envia os encartes")
    run.add_argument("--only", help="mercados separados por virgula (ex.: assai,covabra)")
    run.add_argument("--renderer", choices=render.MODES)
    run.add_argument("--no-send", action="store_true", help="apenas gera os PDFs")
    run.add_argument("--sem-comprimir", action="store_true", help="nao comprime os PDFs")
    run.add_argument("--forcar", action="store_true", help="reenvia mesmo com o encarte identico ao ultimo envio")
    run.add_argument("--data-dir")
    run.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNALEIRO_CONFIG)")
    run.set_defaults(handler=cmd_run)

    show = sub.add_parser("render", help="imprime o texto renderizado de uma URL")
    show.add_argument("url")
    show.add_argument("--renderer", choices=render.MODES)
    show.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNALEIRO_CONFIG)")
    show.set_defaults(handler=cmd_render)

    probe = sub.add_parser("examine-probe", help="debug da descoberta do post do Examine")
    probe.add_argument("--renderer", choices=render.MODES)
    probe.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNALEIRO_CONFIG)")
    probe.set_defaults(handler=cmd_examine_probe)

    serve = sub.add_parser("serve", help="agenda interna: roda a coleta nos horarios configurados")
    serve.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNALEIRO_CONFIG)")
    serve.add_argument("--data-dir")
    serve.add_argument("--no-send", action="store_true", help="apenas gera os PDFs")
    serve.add_argument("--horarios", help="horarios HH:MM separados por virgula (vence config/ambiente)")
    serve.add_argument("--agora", action="store_true", help="executa uma vez e sai (sem esperar a agenda)")
    serve.add_argument("--verificar", action="store_true", help="checa o batimento da agenda (healthcheck)")
    serve.set_defaults(handler=cmd_serve)

    limpar = sub.add_parser("limpar", help="remove coletas antigas de data/ (retencao)")
    limpar.add_argument(
        "--dias",
        type=int,
        help="manter os ultimos N dias (padrao: [retencao] dias, 15); 0 remove tudo que nao e de hoje",
    )
    limpar.add_argument("--dry-run", action="store_true", help="apenas mostra o que seria removido")
    limpar.add_argument("--data-dir")
    limpar.add_argument("--config", help="config.toml (padrao: ./config.toml ou $JORNALEIRO_CONFIG)")
    limpar.set_defaults(handler=cmd_limpar)

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    load_dotenv()
    config_path = localizar_config(args.config)
    config = load_config(config_path)
    data_dir = resolver_data_dir(args, config, config_path)
    try:
        dias_retencao = config_retencao(config)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    keys = select_markets(config, args.only)
    if keys is None:
        return 2

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not args.no_send and not (token and chat_id):
        print("defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    compressao = None if args.sem_comprimir else config_compressao(config)
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
                sha = _sha_assets(result.assets)
                try:
                    row = publish(result, data_dir, today, compressao=compressao)
                except Exception as exc:  # noqa: BLE001 - um mercado nao aborta os demais
                    result.status = "failed"
                    result.error = result.error or describe_error(exc)
                    row = Row(result=result)
                row.sha = sha
                rows.append(row)
                print(f"{key}: {describe(row)}", file=sys.stdout if row.path else sys.stderr)
        finally:
            renderer.close()
            http.close()

        estado_mercados = state.get("mercados")
        if not isinstance(estado_mercados, dict):
            estado_mercados = {}
        for row in rows:
            anterior = estado_mercados.get(row.result.key)
            anterior = anterior if isinstance(anterior, dict) else {}
            if row.path is not None and row.sha:
                row.pular_envio = bool(
                    not args.forcar and anterior.get("enviado") and anterior.get("sha") == row.sha
                )
            if row.path is not None:
                row.aviso = _aviso_do_mercado(row, anterior, today)

        message = summary_message(today, rows)
        print(message)

        falhas: list[str] = []
        if not args.no_send:
            telegram = notify.Telegram(token, chat_id)
            telegram.send_message(message)
            falhas = notify.send_report(telegram, documentos(rows))
        _registrar_envio(state, rows, today, falhas, sem_envio=args.no_send)
        state.save()
        if dias_retencao:
            try:
                apagadas = limpar_coletas(data_dir, dias_retencao)
                if apagadas:
                    print(
                        f"[retencao] {len(apagadas)} coleta(s) removida(s) "
                        f"(retendo {dias_retencao} dias)"
                    )
            except Exception as exc:  # noqa: BLE001 - a retencao nunca derruba o run
                print(f"[retencao] {describe_error(exc)}", file=sys.stderr)
        return exit_code(rows)


def cmd_serve(args: argparse.Namespace) -> int:
    """Agenda interna: roda o `run` nos horarios do config (ou uma vez com `--agora`)."""
    load_dotenv()
    config_path = localizar_config(args.config)
    config = load_config(config_path)
    data_dir = resolver_data_dir(args, config, config_path)
    try:
        params = agenda.parametros(config.get("agenda"))
        if args.horarios:
            params = replace(params, slots=tuple(agenda.horarios(args.horarios)))
    except ValueError as exc:
        print(f"[agenda] {exc}", file=sys.stderr)
        return 2

    estado_path = data_dir / "agenda.json"
    if args.verificar:
        motivo = agenda.verificar(
            State.load(estado_path).data,
            datetime.now(SP),
            saude_janela_s=params.saude_janela_s,
            falhas_limite=params.falhas_limite,
        )
        if motivo:
            print(f"[agenda] {motivo}", file=sys.stderr)
            return 1
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not args.no_send and not (token and chat_id):
        print("defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2

    def avisar(texto: str) -> None:
        # `--no-send` vale tambem para o aviso: teste local nao mexe no Telegram
        if args.no_send or not (token and chat_id):
            print(texto, file=sys.stderr)
            return
        try:
            notify.Telegram(token, chat_id).send_message(texto)
        except Exception as exc:  # noqa: BLE001 - o aviso nunca derruba o loop
            print(f"[agenda] aviso nao enviado: {describe_error(exc)}", file=sys.stderr)

    fila = agenda.Agenda(
        params=params,
        estado_path=estado_path,
        comando=agenda.comando(
            config_path, Path(args.data_dir) if args.data_dir else None, args.no_send
        ),
        log_dir=data_dir.resolve(),  # caminho absoluto no aviso (o /app/data do container)
        avisar=avisar,
    )
    agenda.instalar_sinais()
    return fila.executar_agora() if args.agora else fila.rodar()


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
    if args.dias is None:
        try:
            dias = config_retencao(config)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
    else:
        dias = args.dias
    if dias < 0:
        print("--dias precisa ser >= 0", file=sys.stderr)
        return 2

    alvos = limpar_coletas(data_dir, dias, dry_run=args.dry_run)
    total = sum(tamanho for _, tamanho in alvos)
    for pasta, tamanho in alvos:
        if args.dry_run:
            print(f"seria removida: {pasta} ({tamanho / 1048576:.1f} MB)")
        else:
            print(f"removida: {pasta} ({tamanho / 1048576:.1f} MB)")
    acao = "seriam removidas" if args.dry_run else "removidas"
    print(f"{acao} {len(alvos)} coleta(s), {total / 1048576:.1f} MB (retendo {dias} dia(s))")
    return 0


def limpar_coletas(
    data_dir: Path, dias: int, *, hoje: date | None = None, dry_run: bool = False
) -> list[tuple[Path, int]]:
    """Apaga (ou lista) as coletas de `data/` fora dos ultimos `dias` dias de calendario.

    `dias` conta hoje: `dias=15` mantem a pasta de hoje e as 14 anteriores. Pastas com
    nome que nao e data (ex.: `raw/` solto) e arquivos soltos nunca sao tocados.
    """
    if hoje is None:
        hoje = datetime.now(SP).date()
    limite = hoje - timedelta(days=max(dias - 1, 0))
    if not data_dir.is_dir():
        return []
    alvos: list[tuple[Path, int]] = []
    for pasta in sorted(data_dir.iterdir()):
        if not pasta.is_dir():
            continue
        try:
            dia = date.fromisoformat(pasta.name)
        except ValueError:
            continue
        if dia < limite:
            alvos.append((pasta, _tamanho(pasta)))
    if not dry_run:
        for pasta, _ in alvos:
            shutil.rmtree(pasta)
    return alvos


def _tamanho(pasta: Path) -> int:
    return sum(arquivo.stat().st_size for arquivo in pasta.rglob("*") if arquivo.is_file())


def publish(
    result: MarketResult,
    data_dir: Path,
    today: date,
    *,
    compressao: comprimir.Compressao | None = None,
) -> Row:
    """Grava o PDF do mercado (comprimido) e mede o que ele ocupa."""
    row = Row(result=result)
    if result.status != "ok" or not result.assets:
        return row
    path, pdf, estatisticas = compose.write_result(result, data_dir, today, compressao)
    row.path = path
    row.unit, row.count = measure(result, compose.page_count(pdf))
    if estatisticas is not None:
        row.antes, row.depois = estatisticas.antes, estatisticas.depois
    return row


def documentos(rows: list[Row]) -> list[tuple[str, Path, str]]:
    """Documentos na ordem de envio: o PDF de cada mercado."""
    return [
        (row.result.label, row.path, caption(row))
        for row in rows
        if row.path is not None and not row.pular_envio
    ]


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
    return " | ".join(partes)


def summary_message(today: date, rows: list[Row]) -> str:
    """Mensagem-resumo do Telegram: uma linha por mercado e o total de falhas."""
    lines = [f"Encartes Rio Claro - {today:%d/%m/%Y}"]
    failures: list[str] = []
    for row in rows:
        if row.path is None:
            lines.append(f"{row.result.label} - falha: {row.result.error}")
            failures.append(row.result.label)
            continue
        detail = row.result.validity or row.result.note
        suffix = f" - {detail}" if detail else ""
        aviso = f" | AVISO: {row.aviso}" if row.aviso else ""
        lines.append(f"{row.result.label} - {row.count} {row.unit}{suffix}{aviso}")
    lines.append("Falhas: " + (", ".join(failures) if failures else "nenhuma"))
    return "\n".join(lines)


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


def _sha_assets(assets: list[Asset]) -> str:
    """Impressao digital dos arquivos baixados (base do 'esse encarte ja foi')."""
    if not assets:
        return ""
    digest = hashlib.sha256()
    for asset in assets:
        digest.update(asset.suffix.encode("ascii", "ignore"))
        digest.update(b"\x00")
        digest.update(asset.content)
        digest.update(b"\x00")
    return digest.hexdigest()


_DATA_RE = re.compile(r"(\d{2})/(\d{2})(?:/(\d{4}))?")


def _validade_fim(validity: str | None, hoje: date) -> date | None:
    """Ultima data `dd/mm[/aaaa]` do texto de validade (o fim da janela).

    Sem ano no texto, assume o ano corrente; se isso jogar a data mais de 6 meses
    para tras, e virada de ano (encarte de janeiro ainda valido em dezembro).
    """
    if not validity:
        return None
    datas = _DATA_RE.findall(validity)
    if not datas:
        return None
    dia, mes, ano = datas[-1]
    try:
        if ano:
            return date(int(ano), int(mes), int(dia))
        candidato = date(hoje.year, int(mes), int(dia))
    except ValueError:
        return None
    if (hoje - candidato).days > 180:
        try:
            return date(hoje.year + 1, int(mes), int(dia))
        except ValueError:
            return candidato
    return candidato


def _dia_curto(iso: object) -> str:
    try:
        return f"{date.fromisoformat(str(iso)):%d/%m}"
    except ValueError:
        return "?"


def _aviso_do_mercado(row: Row, anterior: dict, today: date) -> str:
    """Avisos de operacao: encarte vencido e envio repetido."""
    avisos: list[str] = []
    fim = _validade_fim(row.result.validity, today)
    if fim is not None and fim < today:
        avisos.append(f"encarte vencido em {fim:%d/%m}")
    if row.pular_envio:
        avisos.append(f"nao reenviado: igual ao de {_dia_curto(anterior.get('dia'))}")
    return "; ".join(avisos)


def _registrar_envio(
    state: State, rows: list[Row], today: date, falhas: list[str], *, sem_envio: bool
) -> None:
    """Anota no estado o sha de cada mercado e se aquele encarte foi enviado."""
    mercados = state.get("mercados")
    if not isinstance(mercados, dict):
        mercados = {}
    for row in rows:
        if row.path is None or not row.sha:
            continue
        key = row.result.key
        anterior = mercados.get(key)
        anterior = anterior if isinstance(anterior, dict) else {}
        enviado = bool(anterior.get("enviado")) and anterior.get("sha") == row.sha
        if not sem_envio and not _falhou_no_envio(row, falhas):
            enviado = True
        mercados[key] = {"sha": row.sha, "dia": today.isoformat(), "enviado": enviado}
    state.set("mercados", mercados)


def _falhou_no_envio(row: Row, falhas: list[str]) -> bool:
    return any(
        nome == row.result.label or nome.startswith(f"{row.result.label} (") for nome in falhas
    )


def localizar_config(explicito: str | None) -> Path:
    """Acha o config.toml: `--config` > `JORNALEIRO_CONFIG` > pasta atual > raiz do repo."""
    if explicito:
        return Path(explicito)
    do_env = os.environ.get("JORNALEIRO_CONFIG", "").strip()
    if do_env:
        return Path(do_env)
    aqui = Path(DEFAULT_CONFIG)
    raiz = Path(__file__).resolve().parents[2]  # src/jornaleiro/cli.py -> raiz do repositorio
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
    config = _override_ambiente(config)
    config.setdefault("renderer", "auto")
    config.setdefault("data_dir", "data")
    config.setdefault("agenda", {})
    config.setdefault("retencao", {})
    config["markets"] = {
        key: MarketCfg(value) for key, value in (config.get("markets") or {}).items()
    }
    return config


PREFIXO_AMBIENTE = "JORNALEIRO__"


def _override_ambiente(config: dict, env: Mapping[str, str] | None = None) -> dict:
    """Aplica `JORNALEIRO__SECAO__CHAVE=valor` (valor lido como TOML) sobre o config.

    Cada segmento vira um nivel do dict (`JORNALEIRO__MARKETS__ASSAI__ENABLED` ->
    `config["markets"]["assai"]["enabled"]`) e o valor do ambiente substitui o do
    arquivo. Valor que nao e TOML valido entra como string crua (`jina`, `/dados`,
    `07:00,19:00`); a validacao de faixa/tipo fica em quem consome. Variaveis com um
    so underscore (`JORNALEIRO_CONFIG`, `JORNALEIRO_NO_SANDBOX`) ficam de fora.
    """
    for nome, cru in (os.environ if env is None else env).items():
        if not nome.startswith(PREFIXO_AMBIENTE):
            continue
        partes = [parte.lower() for parte in nome[len(PREFIXO_AMBIENTE):].split("__")]
        if any(not parte for parte in partes):
            print(f"[config] variavel ignorada: {nome}", file=sys.stderr)
            continue
        valor = cru.strip()
        if not valor:
            continue
        alvo = config
        for parte in partes[:-1]:
            atual = alvo.get(parte)
            if not isinstance(atual, dict):
                atual = {}
                alvo[parte] = atual
            alvo = atual
        alvo[partes[-1]] = _valor_toml(valor)
    return config


def _valor_toml(valor: str) -> object:
    try:
        return tomllib.loads(f"valor = {valor}")["valor"]
    except tomllib.TOMLDecodeError:
        return valor


def config_retencao(config: dict) -> int:
    """Dias de coletas mantidos em `data/` (`[retencao] dias`, padrao 15; 0 desliga)."""
    valor = (config.get("retencao") or {}).get("dias", 15)
    try:
        dias = int(str(valor).strip())
    except (TypeError, ValueError):
        raise ValueError(f"retencao: dias invalido: {valor!r} (esperado inteiro)") from None
    if dias < 0:
        raise ValueError(f"retencao: dias deve ser >= 0 (recebido {valor!r})")
    return dias


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
