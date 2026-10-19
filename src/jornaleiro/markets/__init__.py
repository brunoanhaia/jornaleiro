"""Modulos de coleta por mercado, na ordem de envio."""

from __future__ import annotations

from types import ModuleType

from ..model import Context, MarketCfg, MarketResult, describe_error
from . import assai, atacadao, covabra, examine, savegnago

REGISTRY: dict[str, ModuleType] = {
    "assai": assai,
    "atacadao": atacadao,
    "covabra": covabra,
    "savegnago": savegnago,
    "examine": examine,
}

ORDER: list[str] = list(REGISTRY)


def safe_fetch(module: ModuleType, ctx: Context, cfg: MarketCfg) -> MarketResult:
    """Chama `module.fetch` sem deixar excecao derrubar os outros mercados."""
    try:
        result = module.fetch(ctx, cfg)
    except Exception as exc:  # noqa: BLE001 - falha de um mercado nao aborta os demais
        return MarketResult(
            key=module.KEY,
            label=module.LABEL,
            status="failed",
            error=describe_error(exc),
        )
    result.key = module.KEY
    result.label = module.LABEL
    if result.status == "ok" and not result.assets:
        result.status = "failed"
        result.error = result.error or "nenhum arquivo baixado"
    return result


__all__ = ["REGISTRY", "ORDER", "safe_fetch"]
