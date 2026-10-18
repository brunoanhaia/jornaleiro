"""Testes do cliente GraphQL do site do Examine (sem rede: respostas simuladas)."""

from __future__ import annotations

import json

import pytest

from jornais import site

NO_REAL = {
    "id": "102104",
    "name": "Feijao Carioca Zorzo 1kg",
    "code": "102104",
    "description": None,
    "salePrice": 10.99,
    "stock": 354.0,
    "weighable": False,
    "unitWeight": None,
    "discounts": [
        {"name": "FEIJAO CARIOCA ZORZO 1KG", "value": 3.1, "type": "Aplicativo", "promotion": True, "limit": 2}
    ],
}

NO_PESAVEL = {
    "id": "206097",
    "name": "Feira Pera Willians kg",
    "salePrice": 19.99,
    "stock": None,
    "weighable": True,
    "unitWeight": 100.0,
    "discounts": [],
}


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_produto_a_partir_do_no() -> None:
    produto = site._produto(NO_REAL, "Alimentos Básicos")

    assert (produto.id, produto.nome, produto.preco, produto.categoria) == (
        "102104",
        "Feijao Carioca Zorzo 1kg",
        10.99,
        "Alimentos Básicos",
    )
    assert produto.estoque == 354.0 and produto.pesavel is False
    assert site.desconto_texto(produto.descontos) == "Aplicativo=3.1"


def test_produto_pesavel() -> None:
    produto = site._produto(NO_PESAVEL, "Feira")

    assert produto.pesavel is True and produto.unidade == 100.0
    assert site.desconto_texto(produto.descontos) == ""


def test_produtos_da_categoria_segue_o_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    paginas = [
        {"data": {"products": {"pageInfo": {"hasNextPage": True, "endCursor": "MjA"},
                               "edges": [{"node": {"id": "1", "name": "A", "salePrice": 1.5, "discounts": []}}]}}},
        {"data": {"products": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                               "edges": [{"node": {"id": "2", "name": "B", "salePrice": 2.5, "discounts": []}}]}}},
    ]
    chamadas: list[dict] = []

    def fake_post(url: str, payload: dict, **kwargs) -> FakeResponse:
        chamadas.append({"url": url, "payload": payload, "headers": kwargs.get("headers")})
        return FakeResponse(paginas[len(chamadas) - 1])

    monkeypatch.setattr(site.http, "post_json", fake_post)
    cliente = site.Site(origin="https://exemplo.crescevendas.com", pausa=0)

    produtos = cliente.produtos_da_categoria("274", "Alimentos Básicos")

    assert [(p.id, p.nome) for p in produtos] == [("1", "A"), ("2", "B")]
    assert chamadas[0]["payload"]["variables"] == {"categoryId": "274", "after": None}
    assert chamadas[1]["payload"]["variables"]["after"] == "MjA"
    # o tenant e resolvido pelo Origin/Referer
    assert chamadas[0]["headers"]["Origin"] == "https://exemplo.crescevendas.com"


def test_categorias_segue_o_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    paginas = [
        {"data": {"categories": {"pageInfo": {"hasNextPage": True, "endCursor": "MjA"},
                                 "edges": [{"node": {"id": "274", "name": "Alimentos Básicos"}}]}}},
        {"data": {"categories": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                 "edges": [{"node": {"id": "275", "name": "Bazar e Utilidades"}}]}}},
    ]
    chamadas: list[dict] = []

    def fake_post(url: str, payload: dict, **kwargs) -> FakeResponse:
        chamadas.append(payload)
        return FakeResponse(paginas[len(chamadas) - 1])

    monkeypatch.setattr(site.http, "post_json", fake_post)
    cliente = site.Site(origin="https://exemplo", pausa=0)

    assert cliente.categorias() == [("274", "Alimentos Básicos"), ("275", "Bazar e Utilidades")]
    assert len(chamadas) == 2


def test_catalogo_limita_categorias(monkeypatch: pytest.MonkeyPatch) -> None:
    variacoes: list[dict] = []

    def fake_post(url: str, payload: dict, **kwargs) -> FakeResponse:
        variacoes.append(payload["variables"])
        categoria = payload["variables"].get("categoryId")
        if categoria is None:
            corpo = {"categories": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                    "edges": [{"node": {"id": "274", "name": "A"}},
                                              {"node": {"id": "275", "name": "B"}}]}}
        else:
            corpo = {"products": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                  "edges": [{"node": {"id": categoria, "name": f"prod {categoria}",
                                                      "salePrice": 9.9, "discounts": []}}]}}
        return FakeResponse({"data": corpo})

    monkeypatch.setattr(site.http, "post_json", fake_post)
    cliente = site.Site(origin="https://exemplo", pausa=0)
    vistos: list[tuple[str, int, int]] = []

    produtos = cliente.catalogo(max_categorias=1, ao_progredir=lambda n, q, t: vistos.append((n, q, t)))

    assert [p.nome for p in produtos] == ["prod 274"]
    assert vistos == [("A", 1, 1)]


def test_folhetos_ordem_e_url_absoluta(monkeypatch: pytest.MonkeyPatch) -> None:
    corpo = {"data": {"pamphlets": [
        {"file": "/system/flyers/files/000/348/232/web/1.jpeg", "id": "348232", "title": "Show de Economia 💚"},
        {"file": "/system/flyers/files/000/348/233/web/2.jpeg", "id": "348233", "title": "Show de Economia 💚"},
        {"file": "https://exemplo.com/story.png", "id": "320837", "title": "Sorteio"},
        {"file": "", "id": "1", "title": "sem arquivo"},
    ]}}
    cabecalhos: list[dict] = []

    def fake_post(url: str, payload: dict, **kwargs) -> FakeResponse:
        cabecalhos.append(kwargs.get("headers") or {})
        return FakeResponse(corpo)

    monkeypatch.setattr(site.http, "post_json", fake_post)
    cliente = site.Site(origin="https://superexaminerc.crescevendas.com", pausa=0, token="abc123")

    folhetos = cliente.folhetos()

    assert [(f.id, f.titulo) for f in folhetos] == [
        ("348232", "Show de Economia 💚"),
        ("348233", "Show de Economia 💚"),
        ("320837", "Sorteio"),
    ]
    assert folhetos[0].url == "https://www.crescevendas.com/system/flyers/files/000/348/232/web/1.jpeg"
    assert folhetos[2].url == "https://exemplo.com/story.png"
    assert cabecalhos[0]["Authorization"] == "Bearer abc123"


def test_folhetos_sem_token_nao_manda_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    cabecalhos: list[dict] = []

    def fake_post(url: str, payload: dict, **kwargs) -> FakeResponse:
        cabecalhos.append(kwargs.get("headers") or {})
        return FakeResponse({"data": {"pamphlets": None}})

    monkeypatch.setattr(site.http, "post_json", fake_post)
    cliente = site.Site(origin="https://exemplo", pausa=0)

    assert cliente.folhetos() == []
    assert "Authorization" not in cabecalhos[0]


def test_csv_do_site(tmp_path) -> None:
    from datetime import date

    produtos = [site._produto(NO_REAL, "Alimentos Básicos"), site._produto(NO_PESAVEL, "Feira")]
    json_path, csv_path = site.write(produtos, tmp_path, date(2026, 10, 15))

    linhas = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert linhas[0] == "id;categoria;produto;preco;pesavel;unidade;estoque;descontos"
    assert linhas[1] == "102104;Alimentos Básicos;Feijao Carioca Zorzo 1kg;10.99;nao;;354.0;Aplicativo=3.1"
    assert linhas[2] == "206097;Feira;Feira Pera Willians kg;19.99;sim;100.0;;"
    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["preco"] == 10.99
    assert json_path.name == "examine.json"
