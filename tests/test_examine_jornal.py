"""Testes do encarte oficial do Examine (jornal do site) e do seu fallback."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from jornais import site
from jornais.markets import examine
from jornais.model import Context, MarketCfg
from jornais.state import State

CFG = {
    "site_graphql_jornal": "https://www.crescevendas.com/graphql",
    "site_url": "https://superexaminerc.crescevendas.com/ecommerce",
}


def contexto() -> Context:
    return Context(renderer=None, today_sp=date(2026, 10, 16), state=State(Path("unused.json")))


def test_fetch_site_usa_o_endpoint_do_jornal(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pamphlets` so existe no /graphql principal; no /ecommerce/graphql da erro."""
    chamadas: list[tuple[str, str]] = []

    class SiteFalso:
        def __init__(self, url: str, **kwargs) -> None:
            chamadas.append((url, kwargs.get("token", "")))

        def folhetos(self) -> list[site.Folheto]:
            return [
                site.Folheto(id="1", titulo="Show de Economia 💚", url="https://exemplo.com/1.jpeg"),
                site.Folheto(id="2", titulo="Show de Economia 💚", url="https://exemplo.com/2.jpeg"),
            ]

    monkeypatch.setattr(examine.site, "Site", SiteFalso)
    monkeypatch.setattr(examine.http, "get_bytes", lambda url, **kwargs: b"jpeg")
    monkeypatch.setenv("EXAMINE_TOKEN", "abc123")

    resultado = examine.fetch_site(contexto(), MarketCfg(CFG))

    assert chamadas == [("https://www.crescevendas.com/graphql", "abc123")]
    assert resultado is not None
    assert resultado.status == "ok"
    assert [asset.suffix for asset in resultado.assets] == [".jpeg", ".jpeg"]
    assert resultado.note == "jornal oficial do site (2 pags: Show de Economia 💚)"


def test_fetch_site_sem_token_devolve_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXAMINE_TOKEN", raising=False)

    assert examine.fetch_site(contexto(), MarketCfg(CFG)) is None


def test_fetch_site_com_falha_devolve_none_para_cair_no_instagram(monkeypatch: pytest.MonkeyPatch) -> None:
    class SiteQuebrado:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def folhetos(self):
            raise RuntimeError("graphql: token invalido")

    monkeypatch.setattr(examine.site, "Site", SiteQuebrado)
    monkeypatch.setenv("EXAMINE_TOKEN", "expirado")

    assert examine.fetch_site(contexto(), MarketCfg(CFG)) is None
