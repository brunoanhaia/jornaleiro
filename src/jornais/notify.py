"""Envio via API de bots do Telegram (sendMessage/sendDocument)."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

API_BASE = "https://api.telegram.org/bot{token}/{method}"
MAX_CAPTION = 1024
MAX_DOCUMENT = 50 * 1024 * 1024  # limite do Telegram
BACKOFF = (2.0, 6.0)


class Telegram:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def _call(
        self,
        method: str,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, object, str]] | None = None,
    ) -> dict:
        url = API_BASE.format(token=self.token, method=method)
        last: BaseException | None = None
        for attempt in range(1, 4):
            try:
                resp = httpx.post(url, data=data, files=files, timeout=180.0)
            except httpx.TransportError as exc:
                last = exc
                if attempt == 3:
                    raise
                time.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
                continue

            if (resp.status_code == 429 or resp.status_code >= 500) and attempt < 3:
                time.sleep(self._retry_after(resp, attempt))
                continue

            if resp.status_code >= 400:
                raise RuntimeError(f"telegram {method}: HTTP {resp.status_code} {resp.text[:200]}")

            payload = resp.json()
            if not payload.get("ok"):
                raise RuntimeError(f"telegram {method}: {payload.get('description')}")
            return payload

        raise last  # pragma: no cover - inalcancavel

    @staticmethod
    def _retry_after(resp: httpx.Response, attempt: int) -> float:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        retry_after = (payload.get("parameters") or {}).get("retry_after")
        if retry_after is None:
            retry_after = resp.headers.get("retry-after")
        if retry_after is None:
            return BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
        return float(retry_after)

    def send_message(self, text: str) -> dict:
        return self._call(
            "sendMessage",
            data={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"},
        )

    def send_document(self, path: Path, caption: str) -> dict:
        size = path.stat().st_size
        if size > MAX_DOCUMENT:
            raise RuntimeError(f"{path.name} tem {size} bytes (limite {MAX_DOCUMENT} bytes)")
        with path.open("rb") as handle:
            return self._call(
                "sendDocument",
                data={"chat_id": self.chat_id, "caption": caption[:MAX_CAPTION]},
                files={"document": (path.name, handle, "application/pdf")},
            )


def send_report(tg: Telegram, documents: list[tuple[str, Path, str]]) -> list[str]:
    """Envia cada documento; falha de um nao impede os seguintes.

    Devolve os nomes que falharam e, se houver, manda uma mensagem extra avisando.
    """
    failed: list[str] = []
    for name, path, caption in documents:
        try:
            tg.send_document(path, caption)
            print(f"enviado: {name} ({path.name})")
        except Exception as exc:  # noqa: BLE001 - segue com os demais mercados
            failed.append(name)
            print(f"falha ao enviar {name}: {type(exc).__name__}: {exc}")
    if failed:
        tg.send_message("Falha ao enviar: " + ", ".join(failed))
    return failed
