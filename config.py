"""
Завантаження конфігурації бота: змінні середовища (.env), config/settings.yaml,
config/watchlist.yaml, config/commissions.yaml, config/levels_override.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

from bot.models import Instrument, AssetClass

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

load_dotenv(ROOT_DIR / ".env")


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class RiskSettings:
    deposit: float = 10000.0
    risk_per_trade_pct: float = 0.005          # 0.5% від депозиту (розділ 8.2 алгоритму)
    luft_pct_of_stop: float = 0.20              # люфт ≈20% стопу (Стратегія 1, розділ 3.2)
    rr_tp1: float = 3.0
    rr_tp2: float = 4.0
    rr_tp3: float = 5.0
    tp1_share: float = 0.50
    tp2_share: float = 0.25
    tp3_share: float = 0.25
    breakeven_at_r: float = 2.0                  # перенос стопу в беззбиток після 2R (розділ 9.2)
    breakout_offset_points_min: int = 2          # відступ входу для Пробою: 2-5 пунктів (Стратегія 2, розд.3.3)
    breakout_offset_points_max: int = 5
    breakout_stop_pct_of_price: float = 0.002    # метод 1: 0.2% від ціни
    breakout_stop_points_min: int = 15           # метод 2: 15-25 пунктів
    breakout_stop_points_max: int = 25
    breakout_atr_multiplier: float = 0.3         # метод 3: ATR * 0.3
    false_breakout_offset_points: int = 2         # відступ 1-2 пункти (Стратегія 3, розд. 6.3)
    false_breakout_buffer_points: int = 2
    channel_min_width_stops: float = 6.0          # мінімальна ширина каналу (Стратегія 5, розд. 3.2)
    channel_wide_threshold_stops: float = 15.0
    channel_min_room_stops: float = 4.0           # мінімальний запас ходу (Стратегія 5, розд. 4.2)
    atr_exhausted_pct: float = 0.75               # 75-80% денного ATR — рух вичерпано (розд. 3.4 алгоритму)
    confluence_threshold_stops: float = 1.0        # поріг конфлюенсу рівнів (Ключові рівні дня, розд. 5.1)
    momentum_max_gap_pct: float = 0.005            # гep-фільтр Різкого імпульсу: не більше ≈0.5%
    engulfing_min_bars: int = 3


@dataclass
class ScanSettings:
    poll_interval_minutes: int = 5
    daily_atr_lookback_days: int = 14
    daily_atr_min_days: int = 5
    anomaly_range_multiplier: float = 2.5   # день вважається "паранормальним", якщо range > median*multiplier
    swing_lookback_bars: int = 3            # фрактал: N барів зліва/справа для локального екстремуму
    level_merge_tolerance_pct: float = 0.001  # рівні ближче цього % вважаються одним рівнем


@dataclass
class TelegramSettings:
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = True


@dataclass
class AppConfig:
    risk: RiskSettings = field(default_factory=RiskSettings)
    scan: ScanSettings = field(default_factory=ScanSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    instruments: List[Instrument] = field(default_factory=list)
    commissions: Dict[str, Any] = field(default_factory=dict)
    levels_override: Dict[str, Any] = field(default_factory=dict)


def _instrument_from_dict(d: Dict[str, Any]) -> Instrument:
    return Instrument(
        symbol=d["symbol"],
        display_name=d.get("display_name", d["symbol"]),
        asset_class=AssetClass(d["asset_class"]),
        provider=d.get("provider", "yfinance"),
        point_value=float(d.get("point_value", 0.01)),
        tick_size=d.get("tick_size"),
        enabled_strategies=d.get("enabled_strategies"),
    )


def load_config() -> AppConfig:
    settings_raw = _load_yaml(CONFIG_DIR / "settings.yaml")
    watchlist_raw = _load_yaml(CONFIG_DIR / "watchlist.yaml")
    commissions_raw = _load_yaml(CONFIG_DIR / "commissions.yaml")
    levels_raw = _load_yaml(CONFIG_DIR / "levels_override.yaml")

    risk = RiskSettings(**{**RiskSettings().__dict__, **(settings_raw.get("risk") or {})})
    scan = ScanSettings(**{**ScanSettings().__dict__, **(settings_raw.get("scan") or {})})

    telegram = TelegramSettings(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        enabled=os.getenv("TELEGRAM_ENABLED", "true").lower() != "false",
    )

    instruments: List[Instrument] = []
    for group in ("stocks", "futures", "crypto", "forex"):
        for item in watchlist_raw.get(group, []) or []:
            instruments.append(_instrument_from_dict(item))

    return AppConfig(
        risk=risk,
        scan=scan,
        telegram=telegram,
        instruments=instruments,
        commissions=commissions_raw,
        levels_override=levels_raw,
    )
