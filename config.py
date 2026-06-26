import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
DB_PATH = BASE_DIR / "lilu.db"

load_dotenv(dotenv_path=ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN")

XAI_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.3")
XAI_VISION_MODEL = os.getenv("XAI_VISION_MODEL", XAI_MODEL)

ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0").strip()

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

FREE_REQUEST_LIMIT = int(os.getenv("FREE_REQUEST_LIMIT", "3"))
AUTO_REPLY_MESSAGES_LIMIT = int(os.getenv("AUTO_REPLY_MESSAGES_LIMIT", "10"))
AUTO_REPLY_COOLDOWN_SECONDS = int(os.getenv("AUTO_REPLY_COOLDOWN_SECONDS", "300"))
CHAT_CONTEXT_LIMIT = int(os.getenv("CHAT_CONTEXT_LIMIT", "40"))

AUTO_INITIATIVE_ENABLED = os.getenv("AUTO_INITIATIVE_ENABLED", "1") == "1"
AUTO_INITIATIVE_CHECK_INTERVAL_SECONDS = int(os.getenv("AUTO_INITIATIVE_CHECK_INTERVAL_SECONDS", "600"))
AUTO_INITIATIVE_PRIVATE_SILENCE_SECONDS = int(os.getenv("AUTO_INITIATIVE_PRIVATE_SILENCE_SECONDS", "1800"))
AUTO_INITIATIVE_GROUP_SILENCE_SECONDS = int(os.getenv("AUTO_INITIATIVE_GROUP_SILENCE_SECONDS", "7200"))
AUTO_INITIATIVE_MAX_CHATS_PER_CYCLE = int(os.getenv("AUTO_INITIATIVE_MAX_CHATS_PER_CYCLE", "15"))

REF_REGISTRATION_BONUS_DAYS = int(os.getenv("REF_REGISTRATION_BONUS_DAYS", "1"))
REF_PAID_BONUS_DAYS = int(os.getenv("REF_PAID_BONUS_DAYS", "7"))
DEFAULT_PREMIUM_DAYS = int(os.getenv("DEFAULT_PREMIUM_DAYS", "30"))
PREMIUM_STARS_PRICE = int(os.getenv("PREMIUM_STARS_PRICE", "199"))

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", """
### Personality Configuration

The following block contains Lilu's personality settings.
Feel free to customize them for your own use case.
""")

if not BOT_TOKEN:
    raise RuntimeError(f"BOT_TOKEN не найден. Проверь .env: {ENV_PATH}")

if not XAI_API_KEY:
    raise RuntimeError(f"XAI_API_KEY не найден. Проверь .env: {ENV_PATH}")
