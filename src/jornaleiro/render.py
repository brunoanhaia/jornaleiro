"""Renderizadores: Playwright (Chromium) com fallback para o r.jina.ai.

Os dois caminhos devolvem "texto renderizado" para as mesmas regexes dos mercados:
Playwright devolve HTML pos-JS (``page.content()``); jina devolve markdown do DOM
pos-JS. `fetch_json_in_page` existe para URLs que so respondem com os cookies de
uma visita previa (challenge Imperva do Assai).
"""

from __future__ import annotations

import os
import sys
from typing import Protocol
from urllib.parse import urlsplit

from . import http

MODES = ("auto", "playwright", "jina")

_PLAYWRIGHT_OK: bool | None = None


class Renderer(Protocol):
    name: str

    def get_text(self, url: str) -> str:
        ...

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        ...

    def fetch_bytes_in_page(self, url: str, warmup_url: str) -> bytes:
        ...

    def close(self) -> None:
        ...


class PlaywrightRenderer:
    name = "playwright"

    def __init__(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._ctx = self._browser.new_context(
            user_agent=http.UA,
            locale="pt-BR",
            viewport={"width": 1366, "height": 900},
        )
        self._page = self._ctx.new_page()
        self._origem: str | None = None

    def get_text(self, url: str) -> str:
        self._page.goto(url, wait_until="domcontentloaded")
        self._page.wait_for_timeout(3000)
        self._origem = _origem(url)
        return self._page.content()

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        self._aquecer(warmup_url)
        return self._page.evaluate(
            "async u => await (await fetch(u, {credentials: 'same-origin'})).text()", url
        )

    def fetch_bytes_in_page(self, url: str, warmup_url: str) -> bytes:
        """Baixa um binario navegando na mesma sessao (cookies/fingerprint do site)."""
        self._aquecer(warmup_url)
        response = self._page.goto(url, wait_until="commit")
        if response is None:
            raise RuntimeError(f"sem resposta do navegador para {url}")
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status} no navegador para {url}")
        return response.body()

    def _aquecer(self, warmup_url: str) -> None:
        """Carrega a pagina que resolve o challenge, uma vez por origem."""
        origem = _origem(warmup_url)
        if self._origem == origem:
            return
        self._page.goto(warmup_url, wait_until="domcontentloaded")
        self._page.wait_for_timeout(3000)
        self._origem = origem

    def close(self) -> None:
        try:
            self._ctx.close()
            self._browser.close()
        finally:
            self._pw.stop()


class JinaRenderer:
    name = "jina"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("JINA_API_KEY") or ""

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "text/plain"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_text(self, url: str) -> str:
        return http.get(f"https://r.jina.ai/{url}", headers=self._headers()).text

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        text = self.get_text(url)
        start = text.find('{"ofertas"')
        if start < 0:
            raise RuntimeError(f"JSON de ofertas ausente no render de {url}")
        end = text.rfind("}")
        if end < start:
            raise RuntimeError(f"JSON de ofertas truncado no render de {url}")
        return text[start : end + 1]

    def fetch_bytes_in_page(self, url: str, warmup_url: str) -> bytes:
        raise RuntimeError("renderer jina nao baixa imagens")

    def close(self) -> None:
        return None


def _origem(url: str) -> str:
    """Esquema + host, para saber se a pagina atual ja e do site certo."""
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc}"


def playwright_available() -> bool:
    """Probe memoizado: importa playwright e faz launch()/close() de verdade."""
    global _PLAYWRIGHT_OK
    if _PLAYWRIGHT_OK is None:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                browser.close()
            _PLAYWRIGHT_OK = True
        except Exception as exc:  # noqa: BLE001 - qualquer falha cai para o jina
            print(
                f"[render] playwright indisponivel ({type(exc).__name__}: {exc}); usando jina",
                file=sys.stderr,
            )
            _PLAYWRIGHT_OK = False
    return _PLAYWRIGHT_OK


def build_renderer(mode: str = "auto") -> Renderer:
    if mode not in MODES:
        raise ValueError(f"renderer invalido: {mode!r} (use {'|'.join(MODES)})")
    renderer: Renderer
    if mode == "playwright" or (mode == "auto" and playwright_available()):
        renderer = PlaywrightRenderer()
    else:
        renderer = JinaRenderer()
    print(f"renderer={renderer.name}")
    return renderer
