"""
Стан бота між запусками — зберігається у state.json.

Потрібен для логіки: "не дублювати радар-сповіщення про один і той самий рівень,
поки ціна не відійшла і не повернулась знову (ретест)".

Обмеження MVP: рівень ідентифікується за округленою ціною. Якщо перерахунок рівнів
між запусками трохи зміщує ціну рівня, це може створити новий запис у стані замість
використання старого. Для перших тестів це не критично; можна вдосконалити пізніше
(наприклад, прив'язавши id рівня до кластера індексів свічок, а не лише до ціни).
"""
import json
import os
import config


def load_state() -> dict:
    if not os.path.exists(config.STATE_FILE):
        return {}
    with open(config.STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict):
    with open(config.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _level_key(level_price: float) -> str:
    return f"{level_price:.4f}"


def should_send_radar_alert(state: dict, symbol: str, level_price: float) -> bool:
    """Перевіряє, чи треба слати радар-сповіщення для цього рівня (вперше або після ретесту)."""
    pair_state = state.get(symbol, {})
    level_state = pair_state.get(_level_key(level_price))

    if level_state is None:
        return True  # ще ніколи не сповіщали про цей рівень

    return level_state.get("moved_away", False)  # сповіщаємо знову лише якщо був ретест


def mark_radar_alert_sent(state: dict, symbol: str, level_price: float):
    """Фіксує, що радар-сповіщення щойно надіслано, і скидає прапорець 'відійшла'."""
    pair_state = state.setdefault(symbol, {})
    pair_state[_level_key(level_price)] = {"alerted": True, "moved_away": False}


def mark_moved_away(state: dict, symbol: str, level_price: float):
    """Фіксує, що ціна відійшла від рівня достатньо далеко — наступне наближення буде ретестом."""
    pair_state = state.setdefault(symbol, {})
    key = _level_key(level_price)
    if key in pair_state:
        pair_state[key]["moved_away"] = True


def update_state_for_level(state: dict, symbol: str, level_price: float, current_price: float):
    """
    Оновлює стан для рівня залежно від поточної відстані ціни:
    якщо ціна відійшла далі RETEST_MOVE_AWAY_PCT — позначає рівень як 'готовий до ретесту'.
    """
    dist = abs(current_price - level_price) / level_price * 100
    if dist >= config.RETEST_MOVE_AWAY_PCT:
        mark_moved_away(state, symbol, level_price)
