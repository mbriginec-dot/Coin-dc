"""
Просте персистентне сховище стану (JSON-файл) — щоб бот НЕ надсилав те саме
попередження/сигнал повторно щоцикл сканування (кожні 5 хв). Навмисно без
бази даних: для персонального бота на одному watchlist цього достатньо,
а формат легко переглянути вручну (data/state.json).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from bot.models import FormationAlert, TradeSignal

log = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Не вдалось прочитати %s (%s) — починаємо з чистого стану", self.path, e)
        return {"formations": {}, "signals": {}, "staircase_trailing": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(self.path)

    @staticmethod
    def _formation_key(alert: FormationAlert) -> str:
        direction = alert.direction.value if alert.direction else "NA"
        return f"{alert.instrument.symbol}|{alert.strategy.value}|{direction}|{alert.level_kind}"

    @staticmethod
    def _signal_key(signal: TradeSignal) -> str:
        return f"{signal.instrument.symbol}|{signal.strategy.value}|{signal.direction.value}|{signal.level_kind}"

    def should_send_formation(self, alert: FormationAlert, cooldown_minutes: float = 30.0) -> bool:
        with self._lock:
            key = self._formation_key(alert)
            entry = self._data["formations"].get(key)
            now = alert.ts
            if entry is None:
                return True
            if entry.get("stage") != alert.stage:
                return True
            last_ts = datetime.fromisoformat(entry["ts"])
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            return (now - last_ts).total_seconds() / 60.0 >= cooldown_minutes

    def mark_formation_sent(self, alert: FormationAlert) -> None:
        with self._lock:
            key = self._formation_key(alert)
            self._data["formations"][key] = {"stage": alert.stage, "ts": alert.ts.isoformat()}
            self._save()

    def should_send_signal(self, signal: TradeSignal, cooldown_minutes: float = 240.0) -> bool:
        with self._lock:
            key = self._signal_key(signal)
            entry = self._data["signals"].get(key)
            if entry is None:
                return True
            last_ts = datetime.fromisoformat(entry["ts"])
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            now = signal.ts if signal.ts.tzinfo else signal.ts.replace(tzinfo=timezone.utc)
            # Той самий рівень+напрямок+стратегія повторно не сповіщаємо протягом
            # cooldown_minutes (за замовчуванням 4 год) — уникає спаму на кожному
            # 5-хв опитуванні, поки формально ще виконуються умови сигналу.
            return (now - last_ts).total_seconds() / 60.0 >= cooldown_minutes

    def mark_signal_sent(self, signal: TradeSignal) -> None:
        with self._lock:
            key = self._signal_key(signal)
            self._data["signals"][key] = {
                "ts": signal.ts.isoformat(),
                "entry": signal.order.entry,
                "stop": signal.order.stop_loss,
            }
            self._save()

    # --- Трейлінг-стоп "Сходинок" (Стратегія 6) ---
    def get_staircase_trailing(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._data["staircase_trailing"].get(symbol)

    def set_staircase_trailing(self, symbol: str, state: Dict[str, Any]) -> None:
        with self._lock:
            self._data["staircase_trailing"][symbol] = state
            self._save()
