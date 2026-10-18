"""Modelo comum: assets, resultado por mercado, config de mercado e contexto."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import httpx

# fuso usado em todas as datas do projeto (validade, "hoje", nome das pastas)
SP = ZoneInfo("America/Sao_Paulo")


@dataclass
class Asset:
    """Um arquivo baixado (PDF ou imagem) de um mercado."""

    url: str
    content: bytes
    kind: str  # "pdf" | "image"
    suffix: str  # ".pdf" | ".jpg"


@dataclass
class MarketResult:
    """Resultado da coleta de um mercado. `status` in ok | failed | skipped."""

    key: str
    label: str
    status: str
    assets: list[Asset] = field(default_factory=list)
    validity: str | None = None
    note: str | None = None
    error: str | None = None


class MarketCfg(dict):
    """Secao [markets.<key>] do config.toml com acesso por atributo."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


@dataclass
class Context:
    """Estado compartilhado de uma execucao."""

    renderer: Any  # jornais.render.Renderer
    today_sp: date
    state: Any  # jornais.state.State


def describe_error(exc: BaseException) -> str:
    """Mensagem curta e estavel para o resumo/nota do mercado."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return f"{type(exc).__name__}: {exc}"
