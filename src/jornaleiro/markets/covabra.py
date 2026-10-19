"""Covabra - jornal de ofertas da cidade (card da VTEX -> PDF no Google Drive)."""

from __future__ import annotations

import html as html_lib
import re

from .. import http
from ..model import Asset, Context, MarketCfg, MarketResult

KEY = "covabra"
LABEL = "Covabra"

LINK_CLASS = '<div class="covabra-jornal-ofertas-0-x-link">'
DRIVE_DOWNLOAD = "https://drive.google.com/uc?export=download&id={file_id}"
_DRIVE_ID = re.compile(r"uc\?export=download&id=([A-Za-z0-9_-]+)")


def fetch(ctx: Context, cfg: MarketCfg) -> MarketResult:
    page = http.get(cfg.page_url).text
    unescaped = html_lib.unescape(page)

    file_id = _drive_id(unescaped, cfg.city)
    if file_id is None:
        return MarketResult(
            key=KEY,
            label=LABEL,
            status="failed",
            error=f"card de {cfg.city} ausente em /jornal-de-ofertas",
        )

    content = _download(file_id)
    validity = _validity(unescaped, file_id, cfg.city)
    asset = Asset(url=DRIVE_DOWNLOAD.format(file_id=file_id), content=content, kind="pdf", suffix=".pdf")
    return MarketResult(key=KEY, label=LABEL, status="ok", assets=[asset], validity=validity)


def _drive_id(unescaped: str, city: str) -> str | None:
    for block in unescaped.split(LINK_CLASS)[1:]:
        if f'alt="{city}"' not in block:
            continue
        match = _DRIVE_ID.search(block)
        if match:
            return match.group(1)
    return None


def _download(file_id: str) -> bytes:
    url = DRIVE_DOWNLOAD.format(file_id=file_id)
    response = http.get(url)
    body = response.content

    # arquivo grande: o Drive responde uma pagina HTML com o campo `confirm`
    if _is_html(response, body) and b"confirm=" in body:
        response = http.get(f"{url}&confirm=t")
        body = response.content

    if _is_html(response, body):
        raise RuntimeError(f"Google Drive devolveu HTML em vez do PDF (id {file_id})")
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"resposta do Google Drive nao comeca com %PDF (id {file_id})")
    return body


def _is_html(response, body: bytes) -> bool:
    content_type = response.headers.get("content-type", "")
    return content_type.startswith("text/html") or body.lstrip()[:1] == b"<"


def _validity(unescaped: str, file_id: str, city: str) -> str | None:
    """O JSON embutido da pagina traz title/subtitle por cidade (ex.: `15/10 - 21/10`)."""
    text = unescaped.replace("\\u002F", "/").replace("\\/", "/")
    for match in re.finditer(r'"title":"' + re.escape(city) + r'"', text):
        segment = text[max(0, match.start() - 600) : match.start()]
        if file_id not in segment:
            continue
        subtitle = re.search(r'"subtitle":"([^"]*)"', text[match.end() : match.end() + 300])
        if subtitle:
            return html_lib.unescape(subtitle.group(1))
    return None
