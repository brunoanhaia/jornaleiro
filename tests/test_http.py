"""Testes do cliente HTTP compartilhado (sem rede: cliente falso)."""

from __future__ import annotations

import httpx
import pytest

from jornais import http

URL = "https://exemplo.test/pagina"


class ClienteFalso:
    """Substitui httpx.Client: registra as chamadas e devolve respostas prontas."""

    def __init__(self, respostas: list) -> None:
        self.respostas = respostas
        self.chamadas: list[dict] = []

    def request(self, method: str, url: str, headers=None, **kwargs) -> httpx.Response:
        self.chamadas.append({"method": method, "url": url, "headers": headers, **kwargs})
        resultado = self.respostas[min(len(self.chamadas) - 1, len(self.respostas) - 1)]
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


def resposta(status: int, url: str = URL, **kwargs) -> httpx.Response:
    """Resposta httpx de verdade, com `request` preenchido p/ raise_for_status()."""
    return httpx.Response(status, request=httpx.Request("GET", url), **kwargs)


def test_get_200_devolve_resposta_e_get_bytes_o_conteudo(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso([
        resposta(200, json={"ok": True}),  # json= ja define content-type application/json
        resposta(200, content=b"conteudo-bruto"),
    ])
    monkeypatch.setattr(http, "client", lambda: cliente)

    resp = http.get(URL, headers={"X-Teste": "1"}, expect="application/json")

    assert resp.json() == {"ok": True}
    assert cliente.chamadas[0]["method"] == "GET"
    assert cliente.chamadas[0]["headers"]["X-Teste"] == "1"

    assert http.get_bytes(URL) == b"conteudo-bruto"
    assert len(cliente.chamadas) == 2


def test_erro_de_transporte_tenta_de_novo_com_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso([
        httpx.TransportError("conexao caiu"),
        httpx.TransportError("conexao caiu de novo"),
        resposta(200, json={"ok": True}),
    ])
    monkeypatch.setattr(http, "client", lambda: cliente)
    sleeps: list[float] = []
    monkeypatch.setattr(http.time, "sleep", sleeps.append)

    resp = http.get(URL)

    assert resp.json() == {"ok": True}
    assert len(cliente.chamadas) == 3
    assert sleeps == [2.0, 6.0]  # http.BACKOFF entre as tentativas


def test_429_e_5xx_sao_tentados_de_novo_e_falham_na_ultima(monkeypatch: pytest.MonkeyPatch) -> None:
    for status in (429, 503):
        cliente = ClienteFalso([resposta(status) for _ in range(3)])
        monkeypatch.setattr(http, "client", lambda: cliente)
        sleeps: list[float] = []
        monkeypatch.setattr(http.time, "sleep", sleeps.append)

        with pytest.raises(httpx.HTTPStatusError):
            http.get(URL)

        assert len(cliente.chamadas) == 3
        assert sleeps == [2.0, 6.0]  # so as duas primeiras tentativas sao retridas


def test_content_type_inesperado_levanta_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso([
        resposta(200, content="<html></html>", headers={"content-type": "text/html"}),
    ])
    monkeypatch.setattr(http, "client", lambda: cliente)

    with pytest.raises(RuntimeError, match="content-type inesperado"):
        http.get(URL, expect="application/json")


def test_retries_zero_e_rejeitado(monkeypatch: pytest.MonkeyPatch) -> None:
    def cliente_que_nao_deve_ser_usado() -> ClienteFalso:
        raise AssertionError("o cliente nao deveria ser usado com retries=0")

    monkeypatch.setattr(http, "client", cliente_que_nao_deve_ser_usado)

    with pytest.raises(ValueError, match="retries"):
        http.get(URL, retries=0)


def test_post_json_manda_payload_e_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso([resposta(200, json={"data": {}})])
    monkeypatch.setattr(http, "client", lambda: cliente)

    http.post_json(
        URL,
        {"query": "consulta", "variables": {"id": "1"}},
        headers={"Authorization": "Bearer token"},
    )

    chamada = cliente.chamadas[0]
    assert chamada["method"] == "POST"
    assert chamada["json"] == {"query": "consulta", "variables": {"id": "1"}}
    assert chamada["headers"]["Authorization"] == "Bearer token"
