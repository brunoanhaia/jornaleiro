"""Testes dos renderizadores (sem navegador: jina com http falso)."""

from __future__ import annotations

import builtins
import json
from typing import Any

import pytest

from jornaleiro import render


class RespostaFalsa:
    """Substitui a resposta de http.get para o JinaRenderer (só precisa de .text)."""

    def __init__(self, texto: str) -> None:
        self.text = texto


def proibe_import_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    """Faz o teste falhar se algo tentar importar playwright (probe/navegador)."""
    import_real = builtins.__import__

    def vigia(name: str, *args: Any, **kwargs: Any):
        if "playwright" in name:
            raise AssertionError(f"playwright nao deveria ser importado ({name})")
        return import_real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", vigia)


def test_build_renderer_recusa_modo_desconhecido() -> None:
    with pytest.raises(ValueError, match="renderer invalido"):
        render.build_renderer("inexistente")


def test_build_renderer_jina_nao_abre_navegador(monkeypatch: pytest.MonkeyPatch) -> None:
    proibe_import_playwright(monkeypatch)

    renderer = render.build_renderer("jina")

    assert isinstance(renderer, render.JinaRenderer)
    assert renderer.name == "jina"


def test_playwright_available_e_memoizado(monkeypatch: pytest.MonkeyPatch) -> None:
    proibe_import_playwright(monkeypatch)

    monkeypatch.setattr(render, "_PLAYWRIGHT_OK", False)
    assert render.playwright_available() is False

    monkeypatch.setattr(render, "_PLAYWRIGHT_OK", True)
    assert render.playwright_available() is True


def test_build_renderer_auto_cai_para_o_jina_sem_playwright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proibe_import_playwright(monkeypatch)
    monkeypatch.setattr(render, "_PLAYWRIGHT_OK", False)

    renderer = render.build_renderer("auto")

    assert isinstance(renderer, render.JinaRenderer)


def test_fetch_json_in_page_extrai_bloco_de_ofertas(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def get_falso(url: str, **kwargs) -> RespostaFalsa:
        urls.append(url)
        return RespostaFalsa('lixo antes {"ofertas": [{"id": 1}, {"id": 2}]} lixo depois')

    monkeypatch.setattr(render.http, "get", get_falso)
    renderer = render.JinaRenderer()

    texto = renderer.fetch_json_in_page("https://assai.test/ofertas", "https://assai.test/")

    assert json.loads(texto) == {"ofertas": [{"id": 1}, {"id": 2}]}
    assert urls == ["https://r.jina.ai/https://assai.test/ofertas"]


def test_fetch_json_in_page_sem_bloco_levanta_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        render.http, "get", lambda url, **kwargs: RespostaFalsa("pagina sem json de ofertas")
    )
    renderer = render.JinaRenderer()

    with pytest.raises(RuntimeError, match="JSON de ofertas ausente"):
        renderer.fetch_json_in_page("https://assai.test/ofertas", "https://assai.test/")
