"""Testes dos renderizadores (sem navegador: jina com http falso)."""

from __future__ import annotations

import builtins
import json

import pytest

from jornaleiro import render


class RespostaFalsa:
    """Substitui a resposta de http.get para o JinaRenderer (só precisa de .text)."""

    def __init__(self, texto: str) -> None:
        self.text = texto


def test_build_renderer_recusa_modo_desconhecido() -> None:
    with pytest.raises(ValueError, match="renderer invalido"):
        render.build_renderer("inexistente")


def test_build_renderer_usa_o_jina(monkeypatch: pytest.MonkeyPatch) -> None:

    import_real = builtins.__import__

    def vigia(name: str, *args, **kwargs):
        assert "playwright" not in name, "o projeto nao deve importar playwright"
        return import_real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", vigia)

    for modo in ("jina", "auto"):
        renderer = render.build_renderer(modo)
        assert isinstance(renderer, render.JinaRenderer)
        assert renderer.name == "jina"


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
