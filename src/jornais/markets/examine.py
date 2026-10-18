"""Examine - encarte publicado como post do Instagram (@examinesupermercados).

Sem login nao da para listar o perfil, mas a pagina de um post publico e acessivel e
traz o bloco "More posts" com os shortcodes recentes da conta. A cadeia e:

    semente persistida -> shortcodes recentes -> legenda de cada post -> imagem original

A semente e o ultimo post processado (``examine_last_post_url``); os shortcodes ja
vistos ficam em ``examine_seen`` para nao serem baixados de novo.
"""

from __future__ import annotations

import html as html_lib
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import http, site
from ..model import Asset, Context, MarketCfg, MarketResult, describe_error

KEY = "examine"
LABEL = "Examine"

SEED_KEY = "examine_last_post_url"
SEEN_KEY = "examine_seen"

POST_URL = "https://www.instagram.com/p/{code}/"
IMAGE_HEADERS = {"Accept": "image/jpeg,image/webp,*/*"}

_SHORTCODE = re.compile(r"/examinesupermercados/(?:p|reel)/([A-Za-z0-9_-]+)/")
_URL = re.compile(r"https://[^\s\"')\\<>]+")
_MEDIA_HOST = re.compile(r"^https://(?:[a-z0-9-]+\.)*(?:cdninstagram\.com|fbcdn\.net)/")
_RESIZED = re.compile(r"_p\d+x\d+")
_CITY_FILTER = "lojas de rio claro"
_VALIDITY = re.compile(r"de (\d{2}/\d{2}) a (\d{2}/\d{2}/\d{4})")
_POSTED = re.compile(r"(?:on|no|em) ([A-Z][a-z]+) (\d{1,2}), (\d{4})")
_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


@dataclass
class Post:
    code: str
    caption: str
    text: str
    posted: date | None


def fetch(ctx: Context, cfg: MarketCfg) -> MarketResult:
    """Encarte do Examine: jornal oficial do site (com token) e, sem token, o Instagram."""
    oficial = fetch_site(ctx, cfg)
    if oficial is not None:
        return oficial
    return fetch_instagram(ctx, cfg)


def fetch_site(ctx: Context, cfg: MarketCfg) -> MarketResult | None:
    """`pamphlets` da crescevendas: o jornal de ofertas oficial, pagina por pagina.

    Precisa do Bearer do clube (`EXAMINE_TOKEN` no .env). Devolve None quando nao ha
    token ou a consulta falha, para o chamador cair no Instagram.
    """
    token = os.environ.get("EXAMINE_TOKEN", "").strip()
    if not token:
        return None

    cliente = site.Site(
        str(cfg.get("site_graphql_jornal", site.GRAPHQL_PADRAO)),
        origin=str(cfg.get("site_url", "") or "https://superexaminerc.crescevendas.com"),
        token=token,
    )
    try:
        folhetos = cliente.folhetos()
    except Exception as exc:  # noqa: BLE001 - sem token valido, o Instagram resolve
        print(f"[examine] jornal oficial indisponivel ({describe_error(exc)}); usando Instagram")
        return None
    if not folhetos:
        return None

    assets = [
        Asset(
            url=folheto.url,
            content=http.get_bytes(folheto.url, headers=IMAGE_HEADERS),
            kind="image",
            suffix=Path(folheto.url).suffix or ".jpeg",
        )
        for folheto in folhetos
    ]
    titulos = sorted({folheto.titulo for folheto in folhetos if folheto.titulo})
    return MarketResult(
        key=KEY,
        label=LABEL,
        status="ok",
        assets=assets,
        note=f"jornal oficial do site ({len(folhetos)} pags: {'; '.join(titulos)})",
    )


def fetch_instagram(ctx: Context, cfg: MarketCfg) -> MarketResult:
    seed, candidates, matches, broken = collect(ctx, cfg)
    if not candidates:
        return MarketResult(
            key=KEY,
            label=LABEL,
            status="failed",
            error=f"nenhum post de encarte novo (semente: {seed})",
        )

    ctx.state.add_seen(SEEN_KEY, candidates)

    if not matches:
        error = f"nenhum post de encarte novo (semente: {seed})"
        if broken:
            error = f"{error}; {len(broken)} candidatos com erro: {'; '.join(broken)}"
        return MarketResult(key=KEY, label=LABEL, status="failed", error=error)

    chosen = max(matches, key=lambda post: post.posted or date.min)
    notes: list[str] = []
    if chosen.posted is None:
        notes.append("post sem data legivel na legenda")

    urls = image_urls(chosen.text)
    if not urls:
        fallback = og_image(chosen.text)
        if fallback is None:
            return MarketResult(
                key=KEY,
                label=LABEL,
                status="failed",
                error=f"post {POST_URL.format(code=chosen.code)} sem imagem",
            )
        urls = [fallback]
        notes.append("apenas miniatura 640x640 (Instagram)")

    referer = POST_URL.format(code=chosen.code)
    assets = [
        Asset(
            url=url,
            content=http.get_bytes(url, headers={**IMAGE_HEADERS, "Referer": referer}),
            kind="image",
            suffix=".jpg",
        )
        for url in urls
    ]

    ctx.state.set(SEED_KEY, referer)
    return MarketResult(
        key=KEY,
        label=LABEL,
        status="ok",
        assets=assets,
        validity=validity_of(chosen.caption),
        note="; ".join(notes) or None,
    )


def collect(
    ctx: Context, cfg: MarketCfg
) -> tuple[str, list[str], list[Post], list[str]]:
    """(semente, candidatos, posts de encarte, candidatos que falharam)."""
    seed, candidates = discover(ctx, cfg)
    matches: list[Post] = []
    broken: list[str] = []
    for code in candidates:
        try:
            text = ctx.renderer.get_text(POST_URL.format(code=code))
        except Exception as exc:  # noqa: BLE001 - um post ruim nao derruba o mercado
            broken.append(f"{code} ({describe_error(exc)})")
            continue
        caption = extract_caption(text)
        if caption and is_encarte(caption, cfg):
            matches.append(
                Post(code=code, caption=caption, text=text, posted=post_date(caption, text))
            )
    return seed, candidates, matches, broken


def discover(ctx: Context, cfg: MarketCfg) -> tuple[str, list[str]]:
    """Semente atual + shortcodes recentes ainda nao vistos (max `cfg.max_posts`)."""
    seed = ctx.state.get(SEED_KEY) or cfg.seed_url
    codes: list[str] = []
    seed_code = shortcode(seed)
    if seed_code:
        codes.append(seed_code)
    for code in _SHORTCODE.findall(normalize(seed_text(ctx, seed))):
        if code not in codes:
            codes.append(code)
    seen = ctx.state.seen(SEEN_KEY)
    return seed, [code for code in codes if code not in seen][: cfg.max_posts]


def seed_text(ctx: Context, seed: str) -> str:
    return ctx.renderer.get_text(seed)


def shortcode(url: str) -> str | None:
    match = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]+)/?", url)
    return match.group(1) if match else None


def normalize(value: str) -> str:
    """Desfaz escapes usados pelo HTML e pelo markdown.

    O HTML do Instagram traz URLs em JSON com escapes (`\\u002F`, `\\u0025`) e o
    markdown do jina usa `&amp;`; sem decodificar, a URL quebra no meio da query.
    """
    value = re.sub(r"\\+u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
    value = value.replace("\\/", "/")
    return value.replace("&amp;", "&")


def extract_caption(text: str) -> str | None:
    meta = re.search(r'og:description" content="([^"]*)"', text)
    if meta:
        return html_lib.unescape(normalize(meta.group(1))) or None

    title = re.search(r"^Title: (.*?)(?=\n(?:URL Source:|Markdown Content:))", text, re.S | re.M)
    if not title:
        return None
    caption = html_lib.unescape(normalize(title.group(1))).strip()
    marker = 'Instagram: "'
    index = caption.find(marker)
    if index >= 0:
        caption = caption[index + len(marker) :].strip()
        if caption.endswith('"'):
            caption = caption[:-1]
    return caption.strip() or None


def is_encarte(caption: str, cfg: MarketCfg) -> bool:
    lowered = caption.lower()
    return cfg.caption_filter.lower() in lowered and _CITY_FILTER in lowered


def post_date(caption: str | None, text: str) -> date | None:
    """Data do post: da propria legenda ou, no render do jina, da primeira do texto.

    O `og:description` (Playwright, locale pt-BR) traz "no October 15, 2026"; a linha
    `Title:` do jina nao traz data, entao vale a primeira do documento - que e a
    imagem do proprio post, antes do bloco "More posts" com posts antigos.
    """
    if caption:
        found = _parse_posted(_POSTED.search(caption))
        if found is not None:
            return found
    return _parse_posted(_POSTED.search(text))


def _parse_posted(match: re.Match[str] | None) -> date | None:
    if match is None:
        return None
    month = _MONTHS.get(match.group(1))
    if month is None:
        return None
    return date(int(match.group(3)), month, int(match.group(2)))


def validity_of(caption: str) -> str | None:
    match = _VALIDITY.search(caption)
    return f"{match.group(1)} a {match.group(2)}" if match else None


def image_urls(text: str) -> list[str]:
    """URLs das imagens do encarte, na ordem do documento, sem miniaturas perfil/640.

    A mesma imagem aparece em varias resolucoes (mesmo caminho, query diferente):
    a primeira ocorrencia no documento e a original, entao dedupe pelo caminho.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for url in _URL.findall(normalize(text)):
        if not _MEDIA_HOST.match(url):
            continue
        if "/rsrc.php" in url or "t51.82787-19" in url or "s640x640" in url:
            continue
        if _RESIZED.search(url):
            continue
        path = url.split("?")[0]
        if path in seen:
            continue
        seen.add(path)
        urls.append(url)
    return urls


def og_image(text: str) -> str | None:
    match = re.search(r'property="og:image" content="([^"]*)"', text)
    return normalize(html_lib.unescape(match.group(1))) if match else None
