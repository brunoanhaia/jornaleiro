"""Atacadao - folhetos da loja de Rio Claro (storeId 638, slug `rio-claro`)."""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from .. import http
from ..model import Asset, Context, MarketCfg, MarketResult

KEY = "atacadao"
LABEL = "Atacadão"

API = "https://apigw.cloud.carrefour.com.br/api-middleware-flyer-services/api/v2/Store/city"
PAGE_SIZE = 24


def fetch(ctx: Context, cfg: MarketCfg) -> MarketResult:
    url = (
        f"{API}?uf={quote(cfg.uf)}&city={quote(cfg.city)}"
        f"&PageSize={PAGE_SIZE}&pageNumber=1&api-version=2"
    )
    data = http.get(url, headers={"Accept": "application/json"}).json()
    stores = data.get("stores") or []
    if not stores:
        raise RuntimeError(f"nenhuma loja retornada para {cfg.city}/{cfg.uf}")
    store = next((item for item in stores if item.get("slug") == cfg.slug), stores[0])

    flyers = _vigentes(store.get("flyers") or [], ctx.today_sp)
    if not flyers:
        return MarketResult(
            key=KEY,
            label=LABEL,
            status="failed",
            error=f"nenhum folheto vigente para {cfg.slug}",
        )

    assets: list[Asset] = []
    included: list[dict] = []
    total = 0
    for flyer in flyers:
        document = flyer.get("urlFinalDocument")
        if not document:
            continue
        content = http.get_bytes(document)
        if assets and total + len(content) > cfg.max_bytes:
            break
        total += len(content)
        assets.append(Asset(url=document, content=content, kind="pdf", suffix=".pdf"))
        included.append(flyer)

    starts = [d for d in (_bound(flyer, "initial") for flyer in included) if d is not None]
    ends = [d for d in (_bound(flyer, "final") for flyer in included) if d is not None]
    validity = None
    if starts and ends:
        validity = f"{min(starts):%d/%m} a {max(ends):%d/%m}"
    names = [flyer.get("name") or flyer.get("id", "") for flyer in included]

    return MarketResult(
        key=KEY,
        label=LABEL,
        status="ok",
        assets=assets,
        validity=validity,
        note="; ".join(names) or None,
    )


def _vigentes(flyers: list[dict], today: date) -> list[dict]:
    """Folhetos vigentes na data, mais prioritarios primeiro."""
    selected = [flyer for flyer in flyers if _vigente(flyer, today)]
    selected.sort(key=lambda flyer: flyer.get("prioridade") or 0, reverse=True)
    return selected


def _vigente(flyer: dict, today: date) -> bool:
    if flyer.get("exclude"):
        return False
    start = _bound(flyer, "initial")
    end = _bound(flyer, "final")
    return start is not None and end is not None and start <= today <= end


def _bound(flyer: dict, side: str) -> date | None:
    """Data-calendario do campo `validity` (ex.: `2026-10-13T00:00:00Z` -> 13/10).

    O horario nao e convertido de fuso: a rede codifica meia-noite com a data local
    que exibe ao cliente ("Boa do Dia" de hoje vem como hoje `T00:00:00Z`), entao
    converter para America/Sao_Paulo deslocaria a janela em um dia.
    """
    raw = (flyer.get("validity") or {}).get(side)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None
