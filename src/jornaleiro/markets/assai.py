"""Assai Atacadista - ofertas da loja Rio Claro (eid=24/nid=77).

O JSON de ofertas fica atras do challenge Imperva/Incapsula: so responde dentro de
uma pagina ja carregada no mesmo contexto (``fetch_json_in_page``). Sem JSON, cai
para o HTML da pagina de ofertas e extrai as URLs CloudFront.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from urllib.parse import urljoin

from .. import http
from ..model import Asset, Context, MarketCfg, MarketResult, describe_error

KEY = "assai"
LABEL = "Assaí Atacadista"

MAX_OFFERS = 3
_DATE_FORMAT = "%d/%m/%Y"
_IMAGE_HEADERS = {"Accept": "image/jpeg,image/webp,*/*"}
_CLOUDFRONT = re.compile(r"https://[^\"'\s]*cloudfront\.net/RPA/[^\"'\s]*\.jpe?g")


def fetch(ctx: Context, cfg: MarketCfg) -> MarketResult:
    json_error: BaseException | None = None
    pages: list[str] = []
    validity: str | None = None

    try:
        pages, validity = _from_json(ctx, cfg)
    except Exception as exc:  # noqa: BLE001 - fallback pelo HTML da pagina
        json_error = exc

    note: str | None = None
    if not pages and json_error is not None:
        pages = _from_page(ctx.renderer.get_text(cfg.offers_page), cfg.max_paginas)
        if pages:
            note = f"paginas extraidas do HTML da pagina de ofertas ({describe_error(json_error)})"

    if not pages:
        error = f"nenhuma oferta vigente para loja eid={cfg.eid}/nid={cfg.nid}"
        if json_error is not None:
            error = f"{error} (json: {describe_error(json_error)})"
        return MarketResult(key=KEY, label=LABEL, status="failed", error=error)

    assets = [
        Asset(
            url=url,
            content=http.get_bytes(url, headers=_IMAGE_HEADERS),
            kind="image",
            suffix=".jpg",
        )
        for url in pages
    ]
    return MarketResult(
        key=KEY, label=LABEL, status="ok", assets=assets, validity=validity, note=note
    )


def _from_json(ctx: Context, cfg: MarketCfg) -> tuple[list[str], str | None]:
    raw = ctx.renderer.fetch_json_in_page(_uncached(cfg.json_url), cfg.offers_page)
    data = json.loads(_slice_json(raw))

    offers = [
        offer for offer in data.get("ofertas") or [] if _is_vigente(offer, cfg, ctx.today_sp)
    ]
    # mesma ordem do JS do site: destaque desc, depois vigencia mais recente primeiro
    offers.sort(key=lambda offer: (_destaque(offer), _start(offer) or date.min), reverse=True)

    pages: list[str] = []
    validity: str | None = None
    for offer in offers[:MAX_OFFERS]:
        if validity is None and (offer.get("custom_text") or "").strip():
            validity = offer["custom_text"].strip()
        for image in offer.get("images") or []:
            url = image.get("url")
            if url and len(pages) < cfg.max_paginas:
                # algumas campanhas vêm com caminho relativo (`/sites/default/files/...`)
                pages.append(urljoin(cfg.json_url, url))
        if len(pages) >= cfg.max_paginas:
            break
    return pages, validity


def _uncached(url: str) -> str:
    """Evita o objeto de borda do CDN, que fica congelado por semanas.

    Verificado em 15/10/2026: a URL sem query devolvia `Last-Modified: 09/10` (71
    ofertas, nenhuma vigente) e o mesmo arquivo com qualquer query vinha com
    `Last-Modified: 15/10` (149.307 B, campanha vigente).
    """
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={int(time.time())}"


def _slice_json(raw: str) -> str:
    start = raw.find('{"ofertas"')
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("bloco JSON de ofertas ausente")
    return raw[start : end + 1]


def _is_vigente(offer: dict, cfg: MarketCfg, today: date) -> bool:
    if not offer.get("images"):
        return False
    if not any(
        loja.get("eid") == cfg.eid and loja.get("nid") == cfg.nid
        for loja in offer.get("lojas") or []
    ):
        return False
    start, end = _interval(offer)
    return start is not None and end is not None and start <= today <= end


def _interval(offer: dict) -> tuple[date | None, date | None]:
    try:
        start = datetime.strptime(offer["start_date"], _DATE_FORMAT).date()
        end = datetime.strptime(offer["end_date"], _DATE_FORMAT).date()
    except (KeyError, TypeError, ValueError):
        return None, None
    return start, end


def _start(offer: dict) -> date | None:
    return _interval(offer)[0]


def _destaque(offer: dict) -> int:
    try:
        return int(offer.get("destaque") or 0)
    except (TypeError, ValueError):
        return 0


def _from_page(html: str, limit: int) -> list[str]:
    text = html.replace("\\u002F", "/").replace("\\/", "/")
    pages: list[str] = []
    for url in _CLOUDFRONT.findall(text):
        if url not in pages:
            pages.append(url)
        if len(pages) >= limit:
            break
    return pages
