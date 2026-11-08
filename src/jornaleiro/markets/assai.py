"""Assai Atacadista - ofertas da loja Rio Claro (eid=24/nid=77).

O JSON de ofertas fica atras do challenge Imperva/Incapsula: so responde dentro de
uma pagina ja carregada no mesmo contexto (``fetch_json_in_page``). Sem JSON, cai
para o HTML da pagina de ofertas e extrai as URLs CloudFront.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from urllib.parse import urljoin

from .. import http
from ..model import Asset, Context, MarketCfg, MarketResult, data_br, describe_error

KEY = "assai"
LABEL = "Assaí Atacadista"

MAX_OFFERS = 3
_JSON_HEADERS = {"Accept": "application/json,text/plain,*/*", "Referer": "https://www.assai.com.br/"}
_HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.assai.com.br/",
}
_IMAGE_HEADERS = {"Accept": "image/jpeg,image/webp,*/*", "Referer": "https://www.assai.com.br/"}
_CLOUDFRONT = re.compile(r"https://[^\"'\s]*cloudfront\.net/RPA/[^\"'\s]*\.jpe?g")


def fetch(ctx: Context, cfg: MarketCfg) -> MarketResult:
    json_error: BaseException | None = None
    html_error: BaseException | None = None
    pages: list[str] = []
    validity: str | None = None

    try:
        pages, validity = _from_json(ctx, cfg)
    except Exception as exc:  # noqa: BLE001 - fallback pelo HTML da pagina
        json_error = exc

    note: str | None = None
    if not pages and json_error is not None:
        try:
            pages = _from_page(_offers_html(ctx, cfg), cfg.max_paginas)
        except Exception as exc:  # noqa: BLE001 - erro vai para o resumo
            html_error = exc
        if pages:
            note = f"paginas extraidas do HTML da pagina de ofertas ({describe_error(json_error)})"

    if not pages:
        error = f"nenhuma oferta vigente para loja eid={cfg.eid}/nid={cfg.nid}"
        if json_error is not None:
            error = f"{error} (json: {describe_error(json_error)})"
        if html_error is not None:
            error = f"{error} (html: {describe_error(html_error)})"
        return MarketResult(key=KEY, label=LABEL, status="failed", error=error)

    try:
        assets = [
            Asset(url=url, content=_baixar_imagem(ctx, cfg, url), kind="image", suffix=".jpg")
            for url in pages
        ]
    except Exception as exc:  # noqa: BLE001 - erro de download vai para o resumo
        return MarketResult(key=KEY, label=LABEL, status="failed", error=str(exc))

    return MarketResult(
        key=KEY, label=LABEL, status="ok", assets=assets, validity=validity, note=note
    )


def _baixar_imagem(ctx: Context, cfg: MarketCfg, url: str) -> bytes:
    """Baixa uma pagina do encarte por HTTP e, se bloquear, pelo navegador.

    A URL no erro localiza o host do 403 (CloudFront ou `www.assai.com.br`). O segundo
    caminho reaproveita os cookies/fingerprint do challenge ja resolvido pela pagina.
    """
    erros: list[str] = []
    try:
        return http.get_bytes(url, headers=_IMAGE_HEADERS)
    except Exception as exc:  # noqa: BLE001 - tenta pelo renderizador
        erros.append(f"http: {describe_error(exc)}")
    try:
        return ctx.renderer.fetch_bytes_in_page(url, cfg.offers_page)
    except Exception as exc:  # noqa: BLE001 - as duas falhas vao para o resumo
        erros.append(f"renderer: {describe_error(exc)}")
    raise RuntimeError(f"{url} (" + "; ".join(erros) + ")")


def _from_json(ctx: Context, cfg: MarketCfg) -> tuple[list[str], str | None]:
    raw = _json_texto(ctx, cfg)
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


def _json_texto(ctx: Context, cfg: MarketCfg) -> str:
    """Texto do JSON: renderizador (cookies/JS do Imperva) e, se falhar, HTTP direto.

    O 403 do challenge costuma aparecer num dos dois caminhos; tentar o outro evita
    perder a coleta quando o Chromium/Jina esta indisponivel ou bloqueado.
    """
    erros: list[str] = []
    tentativas = (
        ("renderer", lambda: ctx.renderer.fetch_json_in_page(_uncached(cfg.json_url), cfg.offers_page)),
        ("http", lambda: _json_direto(cfg)),
    )
    for fonte, buscar in tentativas:
        try:
            raw = buscar()
            _slice_json(raw)
            return raw
        except Exception as exc:  # noqa: BLE001 - tenta a proxima fonte
            erros.append(f"{fonte}: {describe_error(exc)}")
    raise RuntimeError("json de ofertas indisponivel (" + "; ".join(erros) + ")")


def _json_direto(cfg: MarketCfg) -> str:
    return http.get(_uncached(cfg.json_url), headers=_JSON_HEADERS).text


def _offers_html(ctx: Context, cfg: MarketCfg) -> str:
    """HTML da pagina de ofertas, tentando renderizador e depois HTTP direto."""
    erros: list[str] = []
    tentativas = (
        ("renderer", lambda: ctx.renderer.get_text(cfg.offers_page)),
        ("http", lambda: _html_direto(cfg)),
    )
    for fonte, buscar in tentativas:
        try:
            html = buscar()
        except Exception as exc:  # noqa: BLE001 - tenta a proxima fonte
            erros.append(f"{fonte}: {describe_error(exc)}")
            continue
        if _from_page(html, 1):
            return html
        erros.append(f"{fonte}: pagina sem links de encarte")
    raise RuntimeError("pagina de ofertas indisponivel (" + "; ".join(erros) + ")")


def _html_direto(cfg: MarketCfg) -> str:
    return http.get(cfg.offers_page, headers=_HTML_HEADERS).text


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
        start = data_br(offer["start_date"])
        end = data_br(offer["end_date"])
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
