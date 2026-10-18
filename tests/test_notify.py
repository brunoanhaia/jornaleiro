"""Testes do envio por Telegram (sem rede: _call falso)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from jornais import notify

API = "https://api.telegram.org/bot123/fake"


def resposta(status: int, **kwargs) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", API), **kwargs)


def test_retry_after_vem_do_json_quando_existe() -> None:
    resp = resposta(429, json={"ok": False, "parameters": {"retry_after": 7}})

    assert notify.Telegram._retry_after(resp, 1) == 7.0


def test_retry_after_vem_do_header_na_falta_do_json() -> None:
    resp = resposta(502, headers={"retry-after": "5"})

    assert notify.Telegram._retry_after(resp, 1) == 5.0


def test_retry_after_sem_dicas_usa_o_backoff() -> None:
    resp = resposta(500, json={})

    assert notify.Telegram._retry_after(resp, 1) == 2.0
    assert notify.Telegram._retry_after(resp, 2) == 6.0
    assert notify.Telegram._retry_after(resp, 5) == 6.0  # fica preso no ultimo degrau


def test_send_document_trunca_caption_e_usa_mime_da_extensao(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capturadas: list[dict] = []

    def call_falso(self, method, data=None, files=None) -> dict:
        capturadas.append({"method": method, "data": data, "files": files})
        return {"ok": True}

    monkeypatch.setattr(notify.Telegram, "_call", call_falso)
    tg = notify.Telegram("token", "chat")
    legenda = "x" * 2000

    for nome in ("folheto.pdf", "precos.csv"):
        caminho = tmp_path / nome
        caminho.write_bytes(b"conteudo pequeno")
        tg.send_document(caminho, legenda)

    assert [c["method"] for c in capturadas] == ["sendDocument", "sendDocument"]
    pdf, csv = capturadas
    # caption cortada em notify.MAX_CAPTION
    assert pdf["data"]["caption"] == "x" * notify.MAX_CAPTION
    assert len(pdf["data"]["caption"]) == notify.MAX_CAPTION
    assert pdf["data"]["chat_id"] == "chat"
    # content-type vem da extensao do arquivo (mimetypes)
    assert pdf["files"]["document"][0] == "folheto.pdf"
    assert pdf["files"]["document"][2] == "application/pdf"
    assert csv["files"]["document"][0] == "precos.csv"
    assert csv["files"]["document"][2] == "text/csv"


def test_send_document_recusa_arquivo_acima_do_limite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(notify, "MAX_DOCUMENT", 3)
    chamadas: list[dict] = []

    def call_falso(self, method, data=None, files=None) -> dict:
        chamadas.append(data or {})
        return {"ok": True}

    monkeypatch.setattr(notify.Telegram, "_call", call_falso)
    caminho = tmp_path / "grande.pdf"
    caminho.write_bytes(b"1234")  # 4 bytes > limite de 3

    with pytest.raises(RuntimeError, match="limite"):
        notify.Telegram("token", "chat").send_document(caminho, "legenda")

    assert chamadas == []  # nada foi enviado


def test_send_report_continua_apos_falha_e_avisa(tmp_path: Path) -> None:
    ok = tmp_path / "savegnago.pdf"
    ok.write_bytes(b"pdf")
    quebrado = tmp_path / "examine.csv"
    quebrado.write_bytes(b"csv")
    mensagens: list[str] = []

    class TelegramFalso:
        def send_document(self, path: Path, caption: str) -> dict:
            if path.name == "examine.csv":
                raise RuntimeError("HTTP 400")
            return {"ok": True}

        def send_message(self, text: str) -> dict:
            mensagens.append(text)
            return {"ok": True}

    falhas = notify.send_report(
        TelegramFalso(),
        [("Savegnago", ok, "legenda"), ("Examine", quebrado, "legenda")],
    )

    assert falhas == ["Examine"]
    assert mensagens == ["Falha ao enviar: Examine"]
