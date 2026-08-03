"""
Надсилання повідомлень у Telegram (звичайний Telegram Bot API через requests,
без важких залежностей). Два типи повідомлень:

  1. FormationAlert — РАННЄ попередження: формація почала складатись, ще без
     остаточного сигналу (розділ ТЗ користувача: "надсилати завчасно на початку
     формації").
  2. TradeSignal — підтверджений сигнал з повним розрахунком (ТВХ/стоп/тейк/ATR/
     % пройденого ATR/комісія).
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from bot.models import AssetClass, FormationAlert, STRATEGY_NAMES_UA, TradeSignal

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_ASSET_LABELS = {
    AssetClass.STOCK: "Акція",
    AssetClass.FUTURES: "Ф'ючерс",
    AssetClass.CRYPTO: "Криптовалюта",
    AssetClass.FOREX: "Форекс",
}


def _fmt(value: Optional[float], decimals: int = 5) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".") if decimals > 0 else f"{value:,.0f}"


def _decimals_for(point_value: float) -> int:
    if point_value >= 1:
        return 2
    if point_value >= 0.01:
        return 2
    if point_value >= 0.0001:
        return 5
    return 8


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled and bool(bot_token) and bool(chat_id)
        if enabled and not self.enabled:
            log.warning("Telegram вимкнено: не задано TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID у .env")

    def _send(self, text: str) -> bool:
        if not self.enabled:
            log.info("[Telegram вимкнено] %s", text.replace("\n", " | ")[:200])
            return False
        try:
            resp = requests.post(
                TELEGRAM_API.format(token=self.bot_token),
                data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=10,
            )
            if resp.status_code != 200:
                log.error("Telegram sendMessage помилка %s: %s", resp.status_code, resp.text[:300])
                return False
            return True
        except requests.RequestException as e:
            log.error("Telegram sendMessage виняток: %s", e)
            return False

    def send_formation_alert(self, alert: FormationAlert) -> bool:
        strategy_name = STRATEGY_NAMES_UA.get(alert.strategy, alert.strategy)
        asset_label = _ASSET_LABELS.get(alert.instrument.asset_class, alert.instrument.asset_class)
        decimals = _decimals_for(alert.instrument.point_value)
        direction_txt = f"{alert.direction.value}" if alert.direction else "—"

        price_line = ""
        if alert.current_price is not None:
            dist = alert.current_price - alert.level_price
            price_line = (
                f"Поточна ціна: {_fmt(alert.current_price, decimals)} "
                f"(до рівня: {'+' if dist >= 0 else ''}{_fmt(dist, decimals)})\n"
            )
        notes = alert.extra.get("level_notes") or []
        notes_line = f"Фактори сили рівня: {', '.join(notes)}\n" if notes else ""

        text = (
            f"🔔 <b>МОЖЛИВА ФОРМАЦІЯ</b>\n"
            f"Інструмент: <b>{alert.instrument.display_name}</b> ({asset_label})\n"
            f"Стратегія: <b>{strategy_name}</b>\n"
            f"Напрямок (попередній): {direction_txt}\n"
            f"Рівень: {_fmt(alert.level_price, decimals)} ({alert.level_kind})\n"
            f"{price_line}"
            f"{notes_line}"
            f"Стадія: {alert.stage}\n"
            f"{alert.detail}\n"
            f"<i>Це ще НЕ сигнал на вхід — лише попередження про формацію.</i>\n"
            f"🕒 {alert.ts.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        return self._send(text)

    def send_trade_signal(self, signal: TradeSignal) -> bool:
        strategy_name = STRATEGY_NAMES_UA.get(signal.strategy, signal.strategy)
        asset_label = _ASSET_LABELS.get(signal.instrument.asset_class, signal.instrument.asset_class)
        decimals = _decimals_for(signal.instrument.point_value)
        o = signal.order

        atr_pct_txt = f"{signal.atr_used_pct_today * 100:.0f}%" if signal.atr_used_pct_today is not None else "—"
        limit_line = f"Ліміт-ціна: {_fmt(o.limit_price, decimals)}\n" if o.limit_price is not None else ""
        scenario_line = f"Деталі: {signal.scenario}\n" if signal.scenario else ""
        warn_line = ("⚠️ " + "; ".join(signal.warnings) + "\n") if signal.warnings else ""

        price_line = ""
        if signal.current_price is not None:
            dist = o.entry - signal.current_price
            direction_hint = "вище поточної" if dist > 0 else ("нижче поточної" if dist < 0 else "= поточній")
            price_line = (
                f"Поточна ціна: {_fmt(signal.current_price, decimals)} "
                f"(ТВХ {direction_hint}, Δ={_fmt(abs(dist), decimals)})\n"
            )
        notes = signal.extra.get("level_notes") or []
        notes_line = f"Фактори сили рівня: {', '.join(notes)}\n" if notes else ""

        text = (
            f"✅ <b>СИГНАЛ: {strategy_name}</b>\n"
            f"Інструмент: <b>{signal.instrument.display_name}</b> ({asset_label})\n"
            f"Напрямок: <b>{signal.direction.value}</b>\n"
            f"{scenario_line}"
            f"Ордер: <b>{o.order_type}</b>\n"
            f"{price_line}"
            f"Точка входу: <b>{_fmt(o.entry, decimals)}</b>\n"
            f"{limit_line}"
            f"Stop Loss: <b>{_fmt(o.stop_loss, decimals)}</b> (ΔStop = {_fmt(signal.delta_stop, decimals)})\n"
            f"Take Profit 1 (3R): {_fmt(o.take_profit_1, decimals)}\n"
            f"Take Profit 2 (4R): {_fmt(o.take_profit_2, decimals)}\n"
            f"Take Profit 3 (5R): {_fmt(o.take_profit_3, decimals)}\n"
            f"Обсяг позиції: <b>{o.qty:g}</b>\n"
            f"Ризик: ${signal.risk_money:,.2f} · Фактичне R:R: <b>{signal.rr_actual:.2f}</b>\n"
            f"—\n"
            f"Розрахунковий ATR: {_fmt(signal.atr_value, decimals)}\n"
            f"Пройдено ATR сьогодні: <b>{atr_pct_txt}</b>\n"
            f"Комісія (оцінка): ${signal.commission:,.2f}\n"
            f"Рівень: {_fmt(signal.level_price, decimals)} ({signal.level_kind}), сила рівня: {signal.level_strength}\n"
            f"{notes_line}"
            f"{warn_line}"
            f"🕒 {signal.ts.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        return self._send(text)

    def send_text(self, text: str) -> bool:
        return self._send(text)
