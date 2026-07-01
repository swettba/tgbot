import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите токен от @BotFather."
    )

POLL_TICK_SECONDS = int(os.getenv("POLL_TICK_SECONDS", "60"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
FEED_USER_AGENT = os.getenv(
    "FEED_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) TorrentRSSBot/1.0",
)

DEFAULT_INTERVAL_MINUTES = 15
MIN_INTERVAL_MINUTES = 3
MAX_FEEDS_PER_USER = 30
MAX_CONSECUTIVE_ERRORS_BEFORE_ALERT = 5
