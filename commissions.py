"""Пошук комісії для інструмента з config/commissions.yaml (розділ див. коментарі у файлі)."""
from __future__ import annotations

from typing import Any, Dict

from bot.models import AssetClass, Instrument


def estimate_commission(instrument: Instrument, qty: float, notional: float, commissions_cfg: Dict[str, Any]) -> float:
    per_symbol = (commissions_cfg.get("per_symbol_override") or {}).get(instrument.symbol)
    cfg = per_symbol or commissions_cfg.get(instrument.asset_class.value) or {}
    model = cfg.get("model")

    if model == "per_share":
        return qty * float(cfg.get("per_share_usd", 0.0)) + float(cfg.get("per_trade_usd", 0.0))
    if model == "per_contract":
        return qty * float(cfg.get("per_contract_usd", 0.0)) + float(cfg.get("per_trade_usd", 0.0))
    if model == "per_trade":
        return float(cfg.get("per_trade_usd", 0.0))
    if model in ("percent_taker", "percent"):
        pct = float(cfg.get("percent_taker", cfg.get("percent_of_notional", 0.0)))
        return notional * pct
    if model == "per_lot":
        return float(cfg.get("per_lot_usd", 0.0))
    if model == "spread":
        # Спред закладений у ціну виконання, а не як окрема комісія — повертаємо 0,
        # інформація про типовий спред виводиться окремим рядком у повідомленні.
        return 0.0
    return 0.0


def commission_note(instrument: Instrument, commissions_cfg: Dict[str, Any]) -> str:
    per_symbol = (commissions_cfg.get("per_symbol_override") or {}).get(instrument.symbol)
    cfg = per_symbol or commissions_cfg.get(instrument.asset_class.value) or {}
    return cfg.get("notes", "")
