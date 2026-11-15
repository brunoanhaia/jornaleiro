"""Renderizador: r.jina.ai (HTTP) para as paginas que precisam de JS.

O projeto nao usa navegador. O caminho normal dos mercados e HTTP direto; quando a
pagina exige JavaScript ou responde ao cliente simples com challenge (caso do Assai),
o fallback e o [r.jina.ai](https://r.jina.ai), que devolve o DOM ja renderizado em
markdown — sem Chromium/Firefox, sem Playwright e sem download de browser na imagem.

`JinaRenderer` mantem a mesma interface de antes (`get_text`, `fetch_json_in_page`,
`fetch_bytes_in_page`, `close`), entao os mercados nao mudaram.
"""

from __future__ import annotations

import os
from typing import Protocol

from . import http

MODES = ("auto", "jina")  # `auto` = jina: nao ha mais navegador para escolher


class Renderer(Protocol):
    name: str

    def get_text(self, url: str) -> str:
        ...

    def fetch_json_in_page(self, url: str, _warmup_url: str) -> str:
        ...

    def fetch_bytes_in_page(self, url: str, _warmup_url: str) -> bytes:
        ...

    def close(self) -> None:
        ...


class JinaRenderer:
    """r.jina.ai: renderiza a pagina do lado do servidor e devolve o texto/markdown."""

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

    def fetch_json_in_page(self, url: str, _warmup_url: str) -> str:
        text = self.get_text(url)
        start = text.find('{"ofertas"')
        if start < 0:
            raise RuntimeError(f"JSON de ofertas ausente no render de {url}")
        end = text.rfind("}")
        if end < start:
            raise RuntimeError(f"JSON de ofertas truncado no render de {url}")
        return text[start : end + 1]

    def fetch_bytes_in_page(self, url: str, _warmup_url: str) -> bytes:
        raise RuntimeError("renderer jina nao baixa imagens")

    def close(self) -> None:
        return None


def build_renderer(mode: str = "auto") -> Renderer:
    if mode not in MODES:
        raise ValueError(f"renderer invalido: {mode!r} (use {'|'.join(MODES)})")
    renderer: Renderer = JinaRenderer()
    print(f"renderer={renderer.name}")
    return renderer
