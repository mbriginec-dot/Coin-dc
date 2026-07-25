"""
Центральна конфігурація бота. Параметри стратегії та роботи міняй тут.
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()

# --- API ключі (з .env) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- Ринок ---
QUOTE_CURRENCY = "USDC"          # валюта котирування пар
PAIRS_FILE = "pairs.json"        # редагований тобою список пар

# --- Таймфрейми ---
LEVEL_TIMEFRAME = "1d"           # рівні шукаємо на старшому ТФ (за книгою — найсильніші рівні тут)
SIGNAL_TIMEFRAME = "5m"         # підтвердження сигналу шукаємо на молодшому ТФ
LEVEL_CANDLES_LIMIT = 200        # скільки денних свічок тягнути для пошуку рівнів
SIGNAL_CANDLES_LIMIT = 100       # скільки 15m свічок тягнути для перевірки патерну

# --- Пошук рівнів (за методологією з книги) ---
MIN_TOUCHES_FOR_LEVEL = 2         # мінімум дотиків, щоб вважати ціну рівнем
LEVEL_CLUSTER_TOLERANCE_PCT = 0.3 # % відхилення, в межах якого точки вважаються "тим самим рівнем"
PARABOLIC_CANDLE_MULTIPLIER = 2.0 # у скільки разів свічка має перевищувати середню, щоб вважатись "паранормальною"
ROUND_NUMBER_STRENGTH_BONUS = 1   # бонус до сили рівня за кругле число
TOUCH_STRENGTH_WEIGHT = 1         # вага одного дотику у формулі сили рівня
FALSE_BREAKOUT_STRENGTH_BONUS = 2 # бонус до сили за наявність хибного пробою на рівні

# --- Радар (завчасне попередження) ---
RADAR_DISTANCE_PCT = 0.5          # слати радар-сповіщення, коли ціна на такій % відстані від рівня
RADAR_MIN_LEVEL_STRENGTH = 3      # радар шле лише для рівнів такої сили і вище
RETEST_MOVE_AWAY_PCT = 1.0        # ціна має відійти на цей % від рівня, щоб наступне наближення рахувалось як "ретест"

# --- Ризик-менеджмент (з книги: мінімум 3:1) ---
MIN_RISK_REWARD_RATIO = 3.0
STOP_LOSS_BUFFER_PCT = 0.15       # додатковий відступ стопа за рівень, % від ціни

# --- Індикатори для контексту в повідомленнях ---
RSI_PERIOD = 14

# --- Стан бота ---
STATE_FILE = "state.json"

# --- Частота (для локального запуску циклом; на GitHub Actions керується розкладом) ---
CHECK_INTERVAL_SECONDS = 300


def load_pairs() -> list[str]:
    """Читає список пар з pairs.json (редагованого тобою файлу)."""
    with open(PAIRS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pairs", [])
