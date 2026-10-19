"""Savegnago - encarte semanal da cidade (PDF publicado pela propria rede).

A validade vem do texto impresso do PDF, que e mais util que a data do arquivo
(o CDN continua servindo o encarte antigo depois de vencer). O encarte traz
varias mencoes ("As ofertas deste box sao validas ate sabado - 17/10/2026" no
primeiro box, "Ofertas validas de 15 a 18/10/2026" no fim): vale a maior data,
que e ate quando o encarte inteiro ainda tem algo vigente. Quando essa data ja
passou, a validade sai marcada com `(vencido)` no resumo.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from io import BytesIO

from pypdf import PdfReader

from .. import http
from ..model import Asset, Context, MarketCfg, MarketResult, SP

KEY = "savegnago"
LABEL = "Savegnago"

# linhas de validade do encarte; a data completa pode ser "até sábado - 17/10/2026"
# ou "de 15 a 18/10/2026" (a maior data da soma é a validade do encarte inteiro)
_VALIDADE = re.compile(r"v[aá]lidas?[^\n]*", re.IGNORECASE)
_DATA = re.compile(r"\d{2}/\d{2}/\d{4}")


def fetch(ctx: Context, cfg: MarketCfg) -> MarketResult:
    response = http.get(cfg.pdf_url, expect="application/pdf")
    content = response.content

    note = None
    last_modified = response.headers.get("last-modified")
    if last_modified:
        try:
            moment = parsedate_to_datetime(last_modified).astimezone(SP)
            note = f"arquivo de {moment:%d/%m %H:%M} (America/Sao_Paulo)"
        except (TypeError, ValueError):
            note = None

    asset = Asset(url=cfg.pdf_url, content=content, kind="pdf", suffix=".pdf")
    return MarketResult(
        key=KEY,
        label=LABEL,
        status="ok",
        assets=[asset],
        validity=validade(content, ctx.today_sp),
        note=note,
    )


def validade(pdf: bytes, hoje: date) -> str | None:
    """Maior validade impressa em qualquer pagina do PDF."""
    paginas = PdfReader(BytesIO(pdf)).pages
    return validade_texto("\n".join(pagina.extract_text() or "" for pagina in paginas), hoje)


def validade_texto(texto: str, hoje: date) -> str | None:
    datas: list[date] = []
    for linha in _VALIDADE.findall(texto):
        for achada in _DATA.findall(linha):
            try:
                datas.append(datetime.strptime(achada, "%d/%m/%Y").date())
            except ValueError:
                continue
    if not datas:
        return None
    fim = max(datas)
    aviso = " (vencido)" if fim < hoje else ""
    return f"válido até {fim:%d/%m/%Y}{aviso}"
