"""Testes do encarte oficial do Examine (jornal do site) e do seu fallback."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from jornaleiro.markets import examine
from jornaleiro.model import Context, MarketCfg
from jornaleiro.state import State

CFG = {
    "site_graphql_jornal": "https://www.crescevendas.com/graphql",
    "site_url": "https://superexaminerc.crescevendas.com/ecommerce",
}


class RespostaFalsa:
    """Resposta do POST GraphQL (o `pamphlets` do jornal oficial)."""

    def __init__(self, corpo: dict) -> None:
        self._corpo = corpo

    def json(self) -> dict:
        return self._corpo


def contexto() -> Context:
    return Context(renderer=None, today_sp=date(2026, 10, 16), state=State(Path("unused.json")))


def test_fetch_site_usa_o_endpoint_do_jornal(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pamphlets` so existe no /graphql principal; no /ecommerce/graphql da erro."""
    chamadas: list[tuple[str, str]] = []

    def post_falso(url, payload, **kwargs):
        chamadas.append((url, kwargs.get("headers", {}).get("Authorization", "")))
        return RespostaFalsa(
            {
                "data": {
                    "pamphlets": [
                        {"id": "1", "title": "Show de Economia 💚", "file": "/system/1.jpeg"},
                        {"id": "2", "title": "Show de Economia 💚", "file": "/system/2.jpeg"},
                    ]
                }
            }
        )

    monkeypatch.setattr(examine.http, "post_json", post_falso)
    monkeypatch.setattr(examine.http, "get_bytes", lambda url, **kwargs: b"jpeg")
    monkeypatch.setenv("EXAMINE_TOKEN", "abc123")

    resultado = examine.fetch_site(contexto(), MarketCfg(CFG))

    assert chamadas == [("https://www.crescevendas.com/graphql", "Bearer abc123")]
    assert resultado is not None
    assert resultado.status == "ok"
    assert [asset.suffix for asset in resultado.assets] == [".jpeg", ".jpeg"]
    assert resultado.note == "jornal oficial do site (2 pags: Show de Economia 💚)"


def test_fetch_site_sem_token_devolve_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXAMINE_TOKEN", raising=False)

    assert examine.fetch_site(contexto(), MarketCfg(CFG)) is None


def test_fetch_site_com_falha_devolve_none_para_cair_no_instagram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        examine.http,
        "post_json",
        lambda *args, **kwargs: RespostaFalsa({"errors": [{"message": "token invalido"}]}),
    )
    monkeypatch.setenv("EXAMINE_TOKEN", "expirado")

    assert examine.fetch_site(contexto(), MarketCfg(CFG)) is None
