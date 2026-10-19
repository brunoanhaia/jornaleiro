"""Cliente HTTP compartilhado, com retries e backoff."""

from __future__ import annotations

import time
from typing import Any

import httpx

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

BACKOFF = (2.0, 6.0)

_CLIENT: httpx.Client | None = None


def client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            follow_redirects=True,
            timeout=60.0,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
        )
    return _CLIENT


def close() -> None:
    global _CLIENT
    if _CLIENT is not None:
        _CLIENT.close()
        _CLIENT = None


def get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    expect: str | None = None,
    retries: int = 3,
) -> httpx.Response:
    """GET com ate `retries` tentativas em erro de transporte e 429/5xx.

    `expect`: prefixo de Content-Type exigido; diferente disso, levanta RuntimeError.
    """
    return _request("GET", url, headers=headers, expect=expect, retries=retries)


def post_json(
    url: str,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
    expect: str | None = None,
    retries: int = 3,
) -> httpx.Response:
    """POST de JSON (usado pela API GraphQL do site do Examine)."""
    return _request("POST", url, headers=headers, expect=expect, retries=retries, json=payload)


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    expect: str | None = None,
    retries: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    if retries < 1:
        raise ValueError(f"retries precisa ser >= 1 (recebido {retries})")

    last: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = client().request(method, url, headers=headers, **kwargs)
        except httpx.TransportError as exc:
            last = exc
            if attempt == retries:
                raise
            time.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
            continue

        if (resp.status_code == 429 or resp.status_code >= 500) and attempt < retries:
            time.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
            continue

        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if expect is not None and not content_type.startswith(expect):
            raise RuntimeError(
                f"content-type inesperado em {url}: {content_type!r} (esperado {expect!r})"
            )
        return resp

    raise last  # pragma: no cover - inalcancavel (o loop sempre retorna ou levanta)


def get_bytes(url: str, **kwargs: Any) -> bytes:
    return get(url, **kwargs).content
