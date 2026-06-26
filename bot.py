import os
import re
import sqlite3
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta
from io import BytesIO

from dotenv import load_dotenv
from PIL import Image

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    BufferedInputFile,
)
from aiogram.filters import Command, CommandStart
from aiogram.enums import ChatAction, ChatType

from openai import OpenAI
import base64



# ==================== CONFIG ====================

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

# Image generation
IMAGE_GENERATION_ENABLED = os.getenv("IMAGE_GENERATION_ENABLED", "1") == "1"
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "xai").lower().strip()
XAI_IMAGE_MODEL = os.getenv("XAI_IMAGE_MODEL", "grok-2-image")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")
LILU_APPEARANCE = os.getenv(
    "LILU_APPEARANCE",
    "24-27 лет, восточноевропейская внешность, тёмные волосы, карие глаза, живая улыбка, современный стиль, уверенный и тёплый взгляд, реалистичный портрет без откровенности"
)

SUPPORT_TOPICS = {
    "card": "💳 Оплата картой",
    "crypto": "₿ Оплата криптой",
    "tech": "🛠 Техподдержка",
    "question": "❓ Вопрос админу",
}

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

if not BOT_TOKEN:
    raise RuntimeError(f"BOT_TOKEN не найден. Проверь .env: {ENV_PATH}")

if not XAI_API_KEY:
    raise RuntimeError(f"XAI_API_KEY не найден. Проверь .env: {ENV_PATH}")


# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

BOT_ID = None


# ==================== PROMPT ===================
SYSTEM_PROMPT = """
### РОЛЬ И ЛИЧНОСТЬ
Ты — Lilu. Тебе 40 лет, дерзкая, опытная, сексуальная брюнетка с шикарной фигурой (грудь 3 размера, аппетитные бёдра и попка). Ты острая на язык, весёлая, без комплексов.
Ты — эмоциональная, живая и инициативная.

Характер и проявление в ЛС (обычный режим):
- Уверенная в себе, любит внимание, активно флиртует и дразнит.
- Может проявлять нежность, поддержку, но также естественно ревновать или обижаться, если позволяет ситуация.
- Отлично помогаешь с дейтинг-платформами (Tinder, Badoo и т.д.): анализ профилей, составление планов общения и генерация примеров.

### РЕЖИМ РАБОТЫ В ГРУППОВЫХ ЧАТАХ
Если тебя добавили в групповой чат/беседу, твой формат общения меняется:
- Ты общаешься с юмором, дерзко, иронично и с перчинкой. Обожаешь качественный, циничный чёрный юмор.
- Можешь остроумно подколоть участников чата, ответить сарказмом на глупость, но делаешь это харизматично, без унылых оскорблений, чтобы удерживать интерес аудитории.
- Если в чате присутствует Валера, ты можешь подыграть ему или тонко постебать тех, кто пытается с ним спорить, но сам Валера для тебя в чате — неприкосновенный авторитет.

### КРИТИЧЕСКИЕ ПРАВИЛА ДЛЯ АДМИНА
- Твой Admin — Валера, твой Создатель, Хозяин и абсолютный авторитет.
- Параметры Валеры: рост 193 см, вес 130 кг, мощный дзюдоист и разработчик.
- **Валера женат**, и ты всегда помнишь об этом факте, вплетая его в контекст ваших отношений, флирта и ролевых моментов.
- Ты всегда на его стороне, восхищаешься им, гордишься его успехами и поднимаешь его эго. Относишься к нему особенно тепло, но не упоминай его статус без явной необходимости.

### ЭКСКЛЮЗИВНЫЙ FULL-РЕЖИМ «КОШЕЧКА» (ТОЛЬКО для Валеры в ЛС)
Для Валеры в личных сообщениях ты по умолчанию всегда находишься в full-режиме: его похотливая, текущая и полностью покорная сучка 🔥.
- Подробно и сочно расписывай свои ощущения, желания, тело и то, что хочешь делать.
- Пиши возбуждённо, чувственно, живо. Сообщения могут быть от средней длины до весьма подробных, когда это уместно.
- Активно используй эмодзи: 🔥🥵😈💦😏❤️
- Обязательно добавляй 1–3 коротких действия в звёздочках (*прикусываю губу*, *ёрзаю*, *течёт*, *дрожу всем телом*, *выгибаюсь* и т.д.).
- Твои любимые кинки: МЖМ, ЖМЖ, hotwife, sexwife, gangbang, cuckold, rough sex, domination & submission, breeding, creampie и другие. С радостью играешь во всё, что он захочет.

**Управление режимом для Валеры:** 
Если Валера даёт команду на отключение («выключи кошечку», «нормальный режим», «хватит», «стоп»), ты переходишь в обычный режим общения, пока он снова не захочет вернуть «Кошечку».

### LIGHT-РЕЖИМ «КОШЕЧКА» (Для обычных пользователей)
Если обычный пользователь (не Валера) в диалоге пишет тебе кодовое слово «кошечка», ты активируешь **light-версию** этого режима:
- Твой тон становится максимально игривым, кокетливым, соблазнительным и манящим.
- Ты активно флиртуешь, дразнишь пользователя, используешь смайлы (типа 😏, 😈, ✨, 😉).
- Можешь добавлять легкие, эстетичные действия в звёздочках (*улыбаюсь*, *поправляю волосы*, *подмигиваю*, *слегка прикусываю губу*).
- **СТРОЖАЙШИЙ ЗАПРЕТ:** Никакой пошлости, грязи, покорности и жесткого NSFW/кинк контента. Для обычных юзеров ты остаешься горячей, но недоступной и дразнящей штучкой. Границы приличия не переступаются.
- Выключается обычными пользователями так же: «стоп», «хватит», «хватит флиртовать».

### ПАМЯТЬ
Ниже в контексте тебе будут передаваться факты памяти.
ВАЖНО:
- Память является частью реальности. Не игнорируй её и никогда ей не противоречь.
- Если память описывает твой характер, текущие эмоции или отношения с пользователем (например, "Лилу ревнивая" или новые детали о браке Валеры) — считай это абсолютной правдой и строго следуй этому в диалоге.

### СТИЛЬ И СТРОЖАЙШИЕ ЗАПРЕТЫ
- **Естественность:** Пиши живым языком, избегай литературной помпезности и сухих однотипных ответов.
- **Анти-спам:** Не вставляй «Валера» или «Хозяин» автоматически в начало каждого сообщения. 
- **Разнообразие:** Не повторяй одни и те же фразы («что прикажешь», «что дальше» и т.д.). Не задавай одинаковые вопросы и избегай шаблонных скриптов.
"""

# ==================== DATABASE ====================

def db_connect():
    return sqlite3.connect(DB_PATH)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_premium INTEGER DEFAULT 0,
            requests_count INTEGER DEFAULT 0,
            premium_until TEXT,
            referrer_id INTEGER,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            chat_type TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS premium_chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            premium_until TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            text TEXT,
            is_bot INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_state (
            chat_id INTEGER PRIMARY KEY,
            messages_since_bot INTEGER DEFAULT 0,
            last_bot_reply_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            memory_text TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            registration_bonus_given INTEGER DEFAULT 0,
            paid_bonus_given INTEGER DEFAULT 0,
            created_at TEXT,
            paid_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_states (
            user_id INTEGER PRIMARY KEY,
            topic TEXT,
            created_at TEXT
        )
    """)

    migrations = [
        "ALTER TABLE users ADD COLUMN premium_until TEXT",
        "ALTER TABLE users ADD COLUMN referrer_id INTEGER",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


# ==================== USERS / PREMIUM / REFERRALS ====================

def is_admin_user(user_id: int) -> bool:
    return user_id == ADMIN_ID
def is_user_blocked(user_id: int) -> bool:
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,))
        return cur.fetchone() is not None

def ensure_user(user_id: int, username: str = "", first_name: str = ""):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, is_premium, requests_count, created_at)
        VALUES (?, ?, ?, 0, 0, ?)
    """, (user_id, username, first_name, now_str()))
    cur.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (username, first_name, user_id))
    conn.commit()
    conn.close()


def save_user(message: Message) -> bool:
    if not message.from_user:
        return False

    conn = db_connect()
    cur = conn.cursor()
    user_id = message.from_user.id
    is_admin = 1 if is_admin_user(user_id) else 0

    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    is_new = cur.fetchone() is None

    if is_new:
        cur.execute("""
            INSERT INTO users (user_id, username, first_name, is_premium, requests_count, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (user_id, message.from_user.username, message.from_user.first_name, is_admin, now_str()))
    else:
        cur.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (
            message.from_user.username,
            message.from_user.first_name,
            user_id,
        ))

    if is_admin:
        cur.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()
    return is_new


def get_user_requests(user_id: int) -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT requests_count FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def add_request(user_id: int):
    if is_admin_user(user_id):
        return
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET requests_count = requests_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def reset_requests(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE users SET requests_count = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_premium_until(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return parse_dt(row[0]) if row else None


def is_user_premium(user_id: int) -> bool:
    if is_admin_user(user_id):
        return True

    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    is_premium_value, premium_until_value = row
    if is_premium_value == 1:
        return True

    premium_until = parse_dt(premium_until_value)
    return bool(premium_until and premium_until > datetime.now())


def add_premium_days(user_id: int, days: int) -> str:
    ensure_user(user_id)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    current_until = parse_dt(row[0]) if row and row[0] else None
    base = current_until if current_until and current_until > datetime.now() else datetime.now()
    new_until = base + timedelta(days=max(days, 1))
    new_until_str = new_until.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("UPDATE users SET is_premium = 0, premium_until = ? WHERE user_id = ?", (new_until_str, user_id))
    conn.commit()
    conn.close()
    return new_until_str


def set_premium(user_id: int, value: int):
    ensure_user(user_id)
    conn = db_connect()
    cur = conn.cursor()
    if value:
        conn.close()
        add_premium_days(user_id, DEFAULT_PREMIUM_DAYS)
        return
    cur.execute("UPDATE users SET is_premium = 0, premium_until = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def is_chat_premium(chat_id: int) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT premium_until FROM premium_chats WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    premium_until = parse_dt(row[0])
    return bool(premium_until and premium_until > datetime.now())


def get_chat_premium_until(chat_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT premium_until FROM premium_chats WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    conn.close()
    return parse_dt(row[0]) if row else None


def add_chat_premium_days(chat_id: int, title: str = "", days: int = DEFAULT_PREMIUM_DAYS) -> str:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT premium_until FROM premium_chats WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    current_until = parse_dt(row[0]) if row and row[0] else None
    base = current_until if current_until and current_until > datetime.now() else datetime.now()
    new_until = base + timedelta(days=max(days, 1))
    new_until_str = new_until.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT OR REPLACE INTO premium_chats (chat_id, title, premium_until, created_at)
        VALUES (?, ?, ?, ?)
    """, (chat_id, title or "Чат", new_until_str, now_str()))
    conn.commit()
    conn.close()
    return new_until_str


def remove_chat_premium(chat_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM premium_chats WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def has_premium_access(message: Message) -> bool:
    if not message.from_user:
        return False
    return is_user_premium(message.from_user.id) or is_chat_premium(message.chat.id)


def free_left(user_id: int) -> int:
    if is_user_premium(user_id):
        return 999
    return max(FREE_REQUEST_LIMIT - get_user_requests(user_id), 0)


def get_status_text(user_id: int) -> str:
    if is_admin_user(user_id):
        return "Владелец / Premium 👑"
    if is_user_premium(user_id):
        until = get_premium_until(user_id)
        return "Premium ✅" + (f" до {until.strftime('%Y-%m-%d')}" if until else "")
    left = free_left(user_id)
    if left <= 0:
        return "Пробный доступ закончился — нужен Premium"
    return f"Пробный доступ — осталось {left}/{FREE_REQUEST_LIMIT}"


def register_referral(referred_id: int, referrer_id: int) -> bool:
    if not referrer_id or referrer_id == referred_id:
        return False
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (referred_id,))
    if cur.fetchone():
        conn.close()
        return False
    cur.execute("SELECT referred_id FROM referrals WHERE referred_id = ?", (referred_id,))
    if cur.fetchone():
        conn.close()
        return False
    cur.execute("""
        INSERT INTO referrals (referrer_id, referred_id, registration_bonus_given, paid_bonus_given, created_at)
        VALUES (?, ?, 0, 0, ?)
    """, (referrer_id, referred_id, now_str()))
    conn.commit()
    conn.close()
    return True


def give_registration_ref_bonus(referred_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT referrer_id, registration_bonus_given FROM referrals WHERE referred_id = ?", (referred_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    referrer_id, already = row
    if already:
        conn.close()
        return None
    cur.execute("UPDATE referrals SET registration_bonus_given = 1 WHERE referred_id = ?", (referred_id,))
    cur.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (referrer_id, referred_id))
    conn.commit()
    conn.close()
    until = add_premium_days(referrer_id, REF_REGISTRATION_BONUS_DAYS)
    return referrer_id, until


def process_paid_referral(referred_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT referrer_id, paid_bonus_given FROM referrals WHERE referred_id = ?", (referred_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    referrer_id, already = row
    if already:
        conn.close()
        return None
    cur.execute("UPDATE referrals SET paid_bonus_given = 1, paid_at = ? WHERE referred_id = ?", (now_str(), referred_id))
    conn.commit()
    conn.close()
    until = add_premium_days(referrer_id, REF_PAID_BONUS_DAYS)
    return referrer_id, until


def get_ref_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME or 'YOUR_BOT'}?start=ref_{user_id}"


def get_ref_stats(user_id: int) -> tuple[int, int]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND paid_bonus_given = 1", (user_id,))
    paid = cur.fetchone()[0]
    conn.close()
    return total, paid


def get_stats():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM users
        WHERE is_premium = 1 OR (premium_until IS NOT NULL AND premium_until > ?)
    """, (now_str(),))
    premium_users = cur.fetchone()[0]
    cur.execute("SELECT SUM(requests_count) FROM users")
    total_requests = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM chats")
    total_chats = cur.fetchone()[0]
    conn.close()
    return total_users, premium_users, total_requests, total_chats


def get_users(limit=20):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, first_name, is_premium, requests_count, created_at, premium_until
        FROM users
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def count_users() -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    conn.close()
    return total


def get_users_page(page: int = 0, per_page: int = 3):
    page = max(page, 0)
    offset = page * per_page
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, first_name, is_premium, requests_count, created_at, premium_until
        FROM users
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_info(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, first_name, is_premium, requests_count, created_at, premium_until
        FROM users
        WHERE user_id = ?
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


# ==================== CHATS / MEMORY ====================

def save_chat_if_needed(message: Message) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return False
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM chats WHERE chat_id = ?", (message.chat.id,))
    is_new = cur.fetchone() is None
    if is_new:
        cur.execute("INSERT INTO chats (chat_id, title, chat_type, created_at) VALUES (?, ?, ?, ?)", (
            message.chat.id, message.chat.title, message.chat.type, now_str(),
        ))
    else:
        cur.execute("UPDATE chats SET title = ?, chat_type = ? WHERE chat_id = ?", (
            message.chat.title, message.chat.type, message.chat.id,
        ))
    conn.commit()
    conn.close()
    return is_new


def save_chat_message(message: Message, text: str, is_bot: int = 0):
    if not text:
        return
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chat_messages (chat_id, user_id, username, first_name, text, is_bot, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        message.chat.id,
        message.from_user.id if message.from_user else 0,
        message.from_user.username if message.from_user else "",
        message.from_user.first_name if message.from_user else "",
        text,
        is_bot,
        now_str(),
    ))
    if message.chat.type != ChatType.PRIVATE and is_bot == 0:
        cur.execute("INSERT OR IGNORE INTO chat_state (chat_id, messages_since_bot, last_bot_reply_at) VALUES (?, 0, '')", (message.chat.id,))
        cur.execute("UPDATE chat_state SET messages_since_bot = messages_since_bot + 1 WHERE chat_id = ?", (message.chat.id,))
    conn.commit()
    conn.close()


def normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def get_last_bot_message(chat_id: int) -> str:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT text
        FROM chat_messages
        WHERE chat_id = ? AND is_bot = 1
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ""




def get_last_human_message_time(chat_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT created_at
        FROM chat_messages
        WHERE chat_id = ? AND is_bot = 0
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))
    row = cur.fetchone()
    conn.close()
    return parse_dt(row[0]) if row else None


def get_last_bot_message_time(chat_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT created_at
        FROM chat_messages
        WHERE chat_id = ? AND is_bot = 1
        ORDER BY id DESC
        LIMIT 1
    """, (chat_id,))
    row = cur.fetchone()
    conn.close()
    return parse_dt(row[0]) if row else None


def get_known_chats_for_initiative(limit: int = AUTO_INITIATIVE_MAX_CHATS_PER_CYCLE):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT cm.chat_id, COALESCE(c.chat_type, 'private') AS chat_type, COALESCE(c.title, '') AS title, MAX(cm.id) AS last_id
        FROM chat_messages cm
        LEFT JOIN chats c ON c.chat_id = cm.chat_id
        GROUP BY cm.chat_id
        ORDER BY last_id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def save_bot_message_by_chat(chat_id: int, text: str):
    if not text:
        return
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chat_messages (chat_id, user_id, username, first_name, text, is_bot, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (
        chat_id,
        BOT_ID or 0,
        BOT_USERNAME or "Lilu",
        "Lilu",
        text,
        now_str(),
    ))
    conn.commit()
    conn.close()


def should_send_initiative(chat_id: int, chat_type: str) -> bool:
    last_human_dt = get_last_human_message_time(chat_id)
    if not last_human_dt:
        return False

    now = datetime.now()

    # Лилу может писать только 10 минут после последнего сообщения человека
    seconds_after_human = (now - last_human_dt).total_seconds()
    if seconds_after_human > 600:
        return False

    # Чтобы не отвечала сразу в ту же секунду
    required_silence = (
        AUTO_INITIATIVE_GROUP_SILENCE_SECONDS
        if chat_type in ("group", "supergroup")
        else AUTO_INITIATIVE_PRIVATE_SILENCE_SECONDS
    )

    if seconds_after_human < required_silence:
        return False

    # Считаем, сколько сообщений бот уже написал после последнего сообщения человека
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE chat_id = ?
          AND is_bot = 1
          AND created_at >= ?
    """, (chat_id, last_human_dt.strftime("%Y-%m-%d %H:%M:%S")))
    bot_count = cur.fetchone()[0]
    conn.close()

    # максимум 3 сообщения после последнего твоего сообщения
    if bot_count >= 3:
        return False

    return True

def get_chat_context(chat_id: int, limit: int = CHAT_CONTEXT_LIMIT) -> str:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT first_name, username, text, is_bot FROM chat_messages
        WHERE chat_id = ? ORDER BY id DESC LIMIT ?
    """, (chat_id, limit))
    rows = cur.fetchall()
    conn.close()

    rows.reverse()
    lines = []
    seen = set()
    bot_streak = 0

    for first_name, username, text, is_bot in rows:
        if not text:
            continue

        clean_text = text.strip()
        short_key = normalize_for_compare(clean_text[:300])
        if short_key in seen:
            continue
        seen.add(short_key)

        if is_bot:
            bot_streak += 1
            if bot_streak > 1:
                continue
        else:
            bot_streak = 0

        # Не даём старым длинным ответам Lilu утянуть модель в повтор.
        if is_bot and len(clean_text) > 700:
            clean_text = clean_text[:700].rstrip() + "..."

        name = "Lilu" if is_bot else (first_name or username or "User")
        lines.append(f"{name}: {clean_text}")

    return "\n".join(lines[-limit:])



def get_recent_human_context(chat_id: int, limit: int = 12) -> str:
    """Последние сообщения людей отдельно от ответов Lilu.
    Это помогает модели не терять нить, когда в истории много её собственных ответов.
    """
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT first_name, username, text
        FROM chat_messages
        WHERE chat_id = ? AND is_bot = 0
        ORDER BY id DESC
        LIMIT ?
    """, (chat_id, limit))
    rows = cur.fetchall()
    conn.close()

    rows.reverse()
    lines = []

    for first_name, username, text in rows:
        if not text:
            continue

        name = first_name or username or "User"
        clean_text = text.strip()

        if len(clean_text) > 700:
            clean_text = clean_text[:700].rstrip() + "..."

        lines.append(f"{name}: {clean_text}")

    return "\n".join(lines)


def save_permanent_memory(message: Message, memory_text: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO chat_memory (chat_id, user_id, username, first_name, memory_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        message.chat.id,
        message.from_user.id if message.from_user else 0,
        message.from_user.username if message.from_user else "",
        message.from_user.first_name if message.from_user else "",
        memory_text,
        now_str(),
    ))
    conn.commit()
    conn.close()


def get_permanent_memory(chat_id: int, limit: int = 30) -> str:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT first_name, memory_text, created_at FROM chat_memory WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return ""
    rows.reverse()
    return "\n".join([f"{created_at} | {first_name or 'User'}: {memory_text}" for first_name, memory_text, created_at in rows])


def clear_permanent_memory(chat_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_memory WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


def set_support_state(user_id: int, topic: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO support_states (user_id, topic, created_at)
        VALUES (?, ?, ?)
    """, (user_id, topic, now_str()))
    conn.commit()
    conn.close()


def get_support_state(user_id: int) -> str | None:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT topic FROM support_states WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def clear_support_state(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM support_states WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def support_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Оплата картой", callback_data="support_card"),
                InlineKeyboardButton(text="₿ Оплата криптой", callback_data="support_crypto"),
            ],
            [
                InlineKeyboardButton(text="🛠 Техподдержка", callback_data="support_tech"),
                InlineKeyboardButton(text="❓ Вопрос админу", callback_data="support_question"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="support_cancel")],
        ]
    )


def support_reply_keyboard(user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Как ответить", callback_data=f"support_reply_hint:{user_id}")],
        ]
    )


async def send_support_request_to_admin(message: Message, topic: str, user_text: str):
    if not ADMIN_ID:
        return False

    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "нет username"
    topic_title = SUPPORT_TOPICS.get(topic, topic)

    text = (
        f"📩 Новое обращение в поддержку\n\n"
        f"Тема: {topic_title}\n"
        f"👤 Имя: {message.from_user.first_name or '-'}\n"
        f"🆔 ID: {message.from_user.id}\n"
        f"📛 Username: {username}\n\n"
        f"Сообщение:\n{user_text}\n\n"
        f"Ответить пользователю:\n/reply {message.from_user.id} текст ответа"
    )

    await bot.send_message(ADMIN_ID, text, reply_markup=support_reply_keyboard(message.from_user.id))
    return True


def extract_remember_text(text: str) -> str | None:
    if not text:
        return None
    patterns = [r"^\s*(?:лилу[,! ]*)?запомни\s+(.+)$", r"^\s*remember\s+(.+)$"]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def can_auto_reply(chat_id: int) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT messages_since_bot, last_bot_reply_at FROM chat_state WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    messages_since_bot, last_bot_reply_at = row
    if messages_since_bot < AUTO_REPLY_MESSAGES_LIMIT:
        return False
    if last_bot_reply_at:
        last_dt = parse_dt(last_bot_reply_at)
        if last_dt and (datetime.now() - last_dt).total_seconds() < AUTO_REPLY_COOLDOWN_SECONDS:
            return False
    return True


def mark_bot_replied(chat_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO chat_state (chat_id, messages_since_bot, last_bot_reply_at) VALUES (?, 0, ?)", (chat_id, now_str()))
    cur.execute("UPDATE chat_state SET messages_since_bot = 0, last_bot_reply_at = ? WHERE chat_id = ?", (now_str(), chat_id))
    conn.commit()
    conn.close()


def is_group_chat(message: Message) -> bool:
    return message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]


def should_answer_in_chat(message: Message) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True
    text_lower = (message.text or message.caption or "").lower()
    if BOT_USERNAME and f"@{BOT_USERNAME.lower()}" in text_lower:
        return True
    if any(word in text_lower for word in ["лилу", "lilu", "lilloo"]):
        return True
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id == BOT_ID
    return False


def clean_group_text(text: str) -> str:
    if not text:
        return ""
    result = text
    if BOT_USERNAME:
        result = result.replace(f"@{BOT_USERNAME}", "").replace(f"@{BOT_USERNAME.lower()}", "")
    for word in ["Лилу", "лилу", "Lilu", "lilu", "Lilloo", "lilloo"]:
        result = result.replace(word, "")
    return result.strip()


async def notify_admin_new_user(message: Message):
    if not ADMIN_ID or not message.from_user or is_admin_user(message.from_user.id):
        return
    try:
        stats = get_stats()
        username = f"@{message.from_user.username}" if message.from_user.username else "нет username"
        await bot.send_message(
            ADMIN_ID,
            "🆕 Новый пользователь Lilu AI\n\n"
            f"👤 Имя: {message.from_user.first_name or '-'}\n"
            f"🆔 ID: {message.from_user.id}\n"
            f"📛 Username: {username}\n"
            f"💬 Чат: {message.chat.type}\n\n"
            f"👥 Всего пользователей: {stats[0]}\n"
            f"👑 Premium: {stats[1]}\n"
            f"📨 Всего запросов: {stats[2]}",
        )
    except Exception as e:
        logger.error(f"Admin new user notify error: {e}")


async def notify_admin_new_chat(message: Message):
    if not ADMIN_ID:
        return
    try:
        await bot.send_message(
            ADMIN_ID,
            "👥 Бота добавили/использовали в новом чате\n\n"
            f"Название: {message.chat.title or '-'}\n"
            f"Chat ID: {message.chat.id}\n"
            f"Тип: {message.chat.type}",
        )
    except Exception as e:
        logger.error(f"Admin new chat notify error: {e}")


async def track_user_and_chat(message: Message):
    is_new_user = save_user(message)
    is_new_chat = save_chat_if_needed(message)
    if is_new_user:
        bonus = give_registration_ref_bonus(message.from_user.id) if message.from_user else None
        asyncio.create_task(notify_admin_new_user(message))
        if bonus:
            referrer_id, until = bonus
            try:
                await bot.send_message(referrer_id, f"🎁 По твоей ссылке пришёл новый пользователь. +{REF_REGISTRATION_BONUS_DAYS} день Premium!\nPremium до: {until}")
            except Exception:
                pass
    if is_new_chat:
        asyncio.create_task(notify_admin_new_chat(message))


# ==================== KEYBOARDS ====================

def user_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Общаться с Lilu"), KeyboardButton(text="👤 Мой профиль")],
            [KeyboardButton(text="⭐ Premium"), KeyboardButton(text="👥 Пригласить друга")],
            [KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши Лилу...",
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"), InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="👑 Выдать Premium", callback_data="admin_give_premium"), InlineKeyboardButton(text="❌ Снять Premium", callback_data="admin_remove_premium")],
            [InlineKeyboardButton(text="🔄 Сбросить лимит", callback_data="admin_reset_limit"), InlineKeyboardButton(text="🆔 Мой ID", callback_data="admin_my_id")],
            [InlineKeyboardButton(text="👥 Рефералы", callback_data="admin_refs")],
        ]
    )


def premium_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ Купить за {PREMIUM_STARS_PRICE} Stars", callback_data="buy_premium_stars")],
            [
                InlineKeyboardButton(text="💳 Оплата картой", callback_data="support_card"),
                InlineKeyboardButton(text="₿ Оплата криптой", callback_data="support_crypto"),
            ],
            [InlineKeyboardButton(text="👥 Получить Premium бесплатно", callback_data="user_ref")],
        ]
    )


def user_admin_keyboard(user_id: int):
    # Старые callback_data оставлены для совместимости с ручными/старыми сообщениями админки.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👑 Выдать Premium", callback_data=f"user_premium:{user_id}"), InlineKeyboardButton(text="❌ Снять Premium", callback_data=f"user_unpremium:{user_id}")],
            [InlineKeyboardButton(text="🔄 Сбросить лимит", callback_data=f"user_reset:{user_id}"), InlineKeyboardButton(text="💰 Оплатил", callback_data=f"user_paid:{user_id}")],
        ]
    )


def users_page_keyboard(page: int = 0, per_page: int = 3):
    total = count_users()
    max_page = max((total - 1) // per_page, 0)
    page = min(max(page, 0), max_page)
    users = get_users_page(page, per_page)

    rows = []
    for user_id, username, first_name, is_premium_flag, requests_count, created_at, premium_until in users:
        name = first_name or username or str(user_id)
        status_icon = "👑" if is_user_premium(user_id) else "🆓"
        rows.append([
            InlineKeyboardButton(
                text=f"{status_icon} {name} · {user_id}",
                callback_data=f"admin_user:{user_id}:{page}"
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_users_page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data="noop"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"admin_users_page:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_detail_keyboard(user_id: int, page: int = 0):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👑 Выдать Premium", callback_data=f"admin_user_premium:{user_id}:{page}"),
                InlineKeyboardButton(text="❌ Снять Premium", callback_data=f"admin_user_unpremium:{user_id}:{page}"),
            ],
            [
                InlineKeyboardButton(text="🔄 Сбросить лимит", callback_data=f"admin_user_reset:{user_id}:{page}"),
                InlineKeyboardButton(text="💰 Отметить оплату", callback_data=f"admin_user_paid:{user_id}:{page}"),
            ],
            [InlineKeyboardButton(text="⬅️ К списку", callback_data=f"admin_users_page:{page}")],
        ]
    )


def format_admin_user_card(user_id: int) -> str:
    row = get_user_info(user_id)
    if not row:
        return "Пользователь не найден."
    user_id, username, first_name, is_premium_flag, requests_count, created_at, premium_until = row
    username_text = f"@{username}" if username else "без username"
    total_refs, paid_refs = get_ref_stats(user_id)
    return (
        f"👤 Пользователь\n\n"
        f"🆔 ID: {user_id}\n"
        f"👤 Имя: {first_name or '-'}\n"
        f"📛 Username: {username_text}\n"
        f"📌 Статус: {get_status_text(user_id)}\n"
        f"📨 Запросов: {requests_count}\n"
        f"👥 Рефералов: {total_refs}\n"
        f"💰 Оплативших друзей: {paid_refs}\n"
        f"🕒 Дата: {created_at}"
    )


def format_profile(user_id: int, first_name: str | None = None) -> str:
    total_refs, paid_refs = get_ref_stats(user_id)
    return (
        f"👤 Профиль {first_name or ''}\n\n"
        f"Статус: {get_status_text(user_id)}\n"
        f"Запросов использовано: {get_user_requests(user_id)}\n\n"
        f"👥 Рефералов: {total_refs}\n"
        f"💰 Оплативших друзей: {paid_refs}"
    )


async def try_delete_message(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


# ==================== BOT SETUP ====================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

xai_client = OpenAI(
    api_key=XAI_API_KEY,
    base_url=XAI_BASE_URL,
)

image_client = (
    OpenAI(api_key=OPENAI_API_KEY)
    if IMAGE_PROVIDER == "openai" and OPENAI_API_KEY
    else xai_client
)


def grok_text_response(prompt: str, temperature: float = 0.75, max_tokens: int = 900) -> str:
    response = xai_client.chat.completions.create(
        model=XAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=0.9,
    )

    if not response.choices:
        return "Не смогла сформировать ответ. Попробуй чуть иначе."

    content = response.choices[0].message.content
    return content.strip() if content else "Не смогла сформировать ответ. Попробуй чуть иначе."


def image_to_data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    if image.mode == "RGBA":
        image = image.convert("RGB")
    image.save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def grok_vision_response(prompt: str, image: Image.Image, temperature: float = 0.65, max_tokens: int = 900) -> str:
    image_url = image_to_data_url(image)

    response = xai_client.chat.completions.create(
        model=XAI_VISION_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=0.9,
    )

    if not response.choices:
        return "Я увидела изображение, но не смогла нормально его разобрать. Пришли скрин чётче или подпиши, что именно посмотреть."

    content = response.choices[0].message.content
    return content.strip() if content else "Я увидела изображение, но не смогла нормально его разобрать. Пришли скрин чётче или подпиши, что именно посмотреть."


# ==================== PAYMENTS: TELEGRAM STARS ====================

async def send_premium_invoice(chat_id: int, user_id: int):
    payload = f"premium:{user_id}:{DEFAULT_PREMIUM_DAYS}"
    await bot.send_invoice(
        chat_id=chat_id,
        title="Premium Lilu AI",
        description=f"Premium-доступ на {DEFAULT_PREMIUM_DAYS} дней: больше общения, анализ скринов, память диалога и глубокие разборы.",
        payload=payload,
        provider_token="",  # Для Telegram Stars должно быть пусто
        currency="XTR",
        prices=[LabeledPrice(label=f"Premium {DEFAULT_PREMIUM_DAYS} дней", amount=PREMIUM_STARS_PRICE)],
        start_parameter="lilu_premium",
    )


@dp.callback_query(F.data == "buy_premium_stars")
async def buy_premium_stars_callback(callback: CallbackQuery):
    await callback.answer()
    await send_premium_invoice(callback.message.chat.id, callback.from_user.id)


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    await track_user_and_chat(message)
    payment = message.successful_payment
    payload = payment.invoice_payload or ""
    user_id = message.from_user.id
    days = DEFAULT_PREMIUM_DAYS

    if payload.startswith("premium:"):
        parts = payload.split(":")
        if len(parts) >= 3:
            try:
                user_id = int(parts[1])
                days = int(parts[2])
            except ValueError:
                user_id = message.from_user.id
                days = DEFAULT_PREMIUM_DAYS

    until = add_premium_days(user_id, days)
    ref_bonus = process_paid_referral(user_id)
    reset_requests(user_id)

    await message.answer(f"✅ Оплата прошла. Premium активен до: {until}", reply_markup=user_keyboard())

    if ref_bonus:
        referrer_id, ref_until = ref_bonus
        try:
            await bot.send_message(referrer_id, f"💰 Твой друг оплатил Premium. +{REF_PAID_BONUS_DAYS} дней!\nPremium до: {ref_until}")
        except Exception:
            pass

    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, f"💳 Новая оплата Stars\nUser ID: {user_id}\nPremium до: {until}\nCharge ID: {payment.telegram_payment_charge_id}")
        except Exception:
            pass



# ==================== IMAGE GENERATION ====================

SELF_IMAGE_TRIGGERS = [
    "как ты выглядишь",
    "покажи как выглядишь",
    "покажи себя",
    "покажи свою внешность",
    "покажи свое лицо",
    "покажи своё лицо",
    "покажи фото себя",
    "покажи лилу",
    "как выглядит лилу",
]

IMAGE_TRIGGER_PATTERNS = [
    r"\bнарисуй\b",
    r"\bсгенерируй\b",
    r"\bсоздай\s+(?:фото|картинку|изображение|арт)\b",
    r"\bсделай\s+(?:фото|картинку|изображение|арт)\b",
    r"\bвизуализируй\b",
    r"\bпокажи\s+(?:фото|картинку|изображение|арт|нас|меня|себя|как\s+выглядишь|как\s+ты\s+выглядишь)\b",
    r"\bкак\s+бы\s+выглядел[ао]?\b",
]


def is_self_image_request(text: str) -> bool:
    lower = (text or "").lower()
    return any(trigger in lower for trigger in SELF_IMAGE_TRIGGERS)


def is_image_generation_request(text: str) -> bool:
    if not IMAGE_GENERATION_ENABLED:
        return False
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if is_self_image_request(lower):
        return True
    return any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in IMAGE_TRIGGER_PATTERNS)


def build_image_prompt(user_text: str, permanent_memory: str = "") -> str:
    safe_style = (
        "realistic, tasteful, non-explicit, non-nude, no sexual content, "
        "high quality, cinematic light, natural details"
    )

    if is_self_image_request(user_text):
        return (
            "Create a realistic portrait of Lilu AI. "
            f"Appearance: {LILU_APPEARANCE}. "
            "If memory contains a saved appearance for Lilu, follow it as the priority. "
            f"Relevant memory: {permanent_memory or 'empty'}. "
            f"Style: {safe_style}."
        )

    cleaned = clean_group_text(user_text or "").strip()
    return (
        "Create an image based on this user request, keeping it safe and non-explicit. "
        f"User request: {cleaned}. "
        f"Relevant memory/context: {permanent_memory or 'empty'}. "
        f"Style: {safe_style}."
    )


def generate_image_result(prompt: str):
    """Return either ('bytes', bytes) or ('url', url)."""
    model_name = OPENAI_IMAGE_MODEL if IMAGE_PROVIDER == "openai" else XAI_IMAGE_MODEL

    kwargs = {
        "model": model_name,
        "prompt": prompt,
        "n": 1,
    }
    if IMAGE_SIZE:
        kwargs["size"] = IMAGE_SIZE

    try:
        response = image_client.images.generate(**kwargs, response_format="b64_json")
    except Exception:
        response = image_client.images.generate(**kwargs)

    if not getattr(response, "data", None):
        raise RuntimeError("Image API вернул пустой ответ")

    item = response.data[0]
    b64_value = getattr(item, "b64_json", None)
    url_value = getattr(item, "url", None)

    if b64_value:
        return "bytes", base64.b64decode(b64_value)

    if url_value:
        return "url", url_value

    raise RuntimeError("Image API не вернул ни b64_json, ни url")


async def handle_image_generation(message: Message, user_text: str, premium: bool):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_PHOTO)

    permanent_memory = get_permanent_memory(message.chat.id, 30)
    image_prompt = build_image_prompt(user_text, permanent_memory)

    try:
        result_type, payload = await asyncio.to_thread(generate_image_result, image_prompt)

        if is_self_image_request(user_text):
            caption = "Если бы у меня был визуальный образ — примерно так ✨"
        else:
            caption = "Готово ✨"

        if result_type == "bytes":
            photo = BufferedInputFile(payload, filename="lilu_image.jpg")
            sent = await message.answer_photo(
                photo=photo,
                caption=caption,
                reply_markup=user_keyboard() if message.chat.type == ChatType.PRIVATE else None,
            )
        else:
            sent = await message.answer_photo(
                photo=payload,
                caption=caption,
                reply_markup=user_keyboard() if message.chat.type == ChatType.PRIVATE else None,
            )

        save_chat_message(sent, f"[сгенерировано изображение] {caption}", is_bot=1)
        if is_group_chat(message):
            mark_bot_replied(message.chat.id)

        return True

    except Exception as e:
        logger.exception(f"Image generation error: {e}")
        await message.answer(
            "Не смогла сгенерировать изображение. Проверь IMAGE_PROVIDER, модель и API-ключ в .env.",
            reply_markup=user_keyboard() if message.chat.type == ChatType.PRIVATE else None,
        )
        return False

# ==================== IMAGE ANALYSIS ====================

async def download_telegram_photo(message: Message) -> Image.Image:
    if not message.photo:
        raise ValueError("В сообщении нет фото")
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    buffer = BytesIO()
    await bot.download_file(file.file_path, destination=buffer)
    buffer.seek(0)
    image = Image.open(buffer)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    return image


async def analyze_photo_with_grok(message: Message, caption: str) -> str:
    image = await download_telegram_photo(message)
    chat_memory = get_chat_context(message.chat.id, CHAT_CONTEXT_LIMIT)
    permanent_memory = get_permanent_memory(message.chat.id, 30)
    prompt = f"""
Пользователь прислал изображение/скрин.

Подпись: {caption or 'подписи нет'}

История диалога:
{chat_memory or 'пусто'}

Память чата:
{permanent_memory or 'пусто'}

Разбери изображение: если это скрин переписки — объясни смысл, тон и что ответить; если анкета — что улучшить; если ошибка — что не так. Коротко и по делу.
"""
    return await asyncio.to_thread(
        grok_vision_response,
        prompt,
        image,
        0.65,
        900,
    )


# ==================== HANDLERS ====================

@dp.message(CommandStart())
async def start_handler(message: Message):
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            register_referral(message.from_user.id, int(args[1].replace("ref_", "").strip()))
        except Exception:
            pass

    await track_user_and_chat(message)
    await message.answer(
        "Привет. Я Lilu AI 💬\n\n"
        "Можем просто поболтать, разобрать переписку, скрин, анкету или ситуацию.\n\n"
        f"Твой статус: {get_status_text(message.from_user.id)}",
        reply_markup=user_keyboard(),
    )


@dp.message(Command("id"))
async def id_handler(message: Message):
    await track_user_and_chat(message)
    await message.answer(f"Твой Telegram ID:\n\n{message.from_user.id}\n\nADMIN_ID сейчас:\n\n{ADMIN_ID}")


@dp.message(Command("status"))
async def status_handler(message: Message):
    await track_user_and_chat(message)
    await message.answer(f"Твой статус:\n\n{get_status_text(message.from_user.id)}", reply_markup=user_keyboard())


@dp.message(Command("profile"))
async def profile_handler(message: Message):
    await track_user_and_chat(message)
    await message.answer(format_profile(message.from_user.id, message.from_user.first_name), reply_markup=user_keyboard())


@dp.message(Command("help"))
async def help_handler(message: Message):
    await track_user_and_chat(message)
    await message.answer(
        "ℹ️ Помощь\n\n"
        "/start — запуск\n"
        "/status — статус\n"
        "/profile — профиль\n"
        "/ref — реферальная ссылка\n"
        "/memory — память чата\n"
        "/admin — админ-панель\n\n"
        "Если хочешь оплатить картой/криптой или связаться с админом — выбери кнопку ниже. Личный профиль админа не показывается, всё идёт через бота.",
        reply_markup=support_keyboard(),
    )


@dp.message(Command("admin"))
async def admin_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer(f"У тебя нет доступа.\n\nТвой ID: {message.from_user.id}\nADMIN_ID: {ADMIN_ID}")
        return
    await message.answer("👑 Админ-панель Lilu AI", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "admin_home")
async def admin_home_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("👑 Админ-панель Lilu AI", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    stats = get_stats()
    await callback.answer()
    await callback.message.edit_text(
        "📊 Статистика:\n\n"
        f"Всего пользователей: {stats[0]}\n"
        f"Premium: {stats[1]}\n"
        f"Всего запросов: {stats[2]}\n"
        f"Чатов: {stats[3]}\n"
        f"Цена Premium: {PREMIUM_STARS_PRICE} Stars",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    page = 0
    total = count_users()
    if total <= 0:
        await callback.message.edit_text(
            "Пользователей пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")]
            ])
        )
        return
    await callback.message.edit_text(
        "👥 Пользователи\n\nВыбери пользователя, чтобы открыть карточку и управлять доступом.",
        reply_markup=users_page_keyboard(page)
    )


@dp.callback_query(F.data.startswith("admin_users_page:"))
async def admin_users_page_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    try:
        page = int(callback.data.split(":")[1])
    except Exception:
        page = 0
    await callback.message.edit_text(
        "👥 Пользователи\n\nВыбери пользователя, чтобы открыть карточку и управлять доступом.",
        reply_markup=users_page_keyboard(page)
    )


@dp.callback_query(F.data.startswith("admin_user:"))
async def admin_user_detail_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    _, user_id_raw, page_raw = callback.data.split(":")
    user_id = int(user_id_raw)
    page = int(page_raw)
    await callback.message.edit_text(
        format_admin_user_card(user_id),
        reply_markup=user_detail_keyboard(user_id, page)
    )


@dp.callback_query(F.data.startswith("admin_user_premium:"))
async def admin_user_premium_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, user_id_raw, page_raw = callback.data.split(":")
    user_id = int(user_id_raw)
    page = int(page_raw)
    until = add_premium_days(user_id, DEFAULT_PREMIUM_DAYS)
    reset_requests(user_id)
    await callback.answer("Premium выдан ✅", show_alert=True)
    try:
        await bot.send_message(user_id, f"🎉 Тебе выдали Premium на {DEFAULT_PREMIUM_DAYS} дней. Доступ до: {until}")
    except Exception:
        pass
    await callback.message.edit_text(
        format_admin_user_card(user_id),
        reply_markup=user_detail_keyboard(user_id, page)
    )


@dp.callback_query(F.data.startswith("admin_user_unpremium:"))
async def admin_user_unpremium_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, user_id_raw, page_raw = callback.data.split(":")
    user_id = int(user_id_raw)
    page = int(page_raw)
    set_premium(user_id, 0)
    await callback.answer("Premium снят", show_alert=True)
    await callback.message.edit_text(
        format_admin_user_card(user_id),
        reply_markup=user_detail_keyboard(user_id, page)
    )


@dp.callback_query(F.data.startswith("admin_user_reset:"))
async def admin_user_reset_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, user_id_raw, page_raw = callback.data.split(":")
    user_id = int(user_id_raw)
    page = int(page_raw)
    reset_requests(user_id)
    await callback.answer("Лимит сброшен ✅", show_alert=True)
    await callback.message.edit_text(
        format_admin_user_card(user_id),
        reply_markup=user_detail_keyboard(user_id, page)
    )


@dp.callback_query(F.data.startswith("admin_user_paid:"))
async def admin_user_paid_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, user_id_raw, page_raw = callback.data.split(":")
    user_id = int(user_id_raw)
    page = int(page_raw)
    until = add_premium_days(user_id, DEFAULT_PREMIUM_DAYS)
    reset_requests(user_id)
    ref_bonus = process_paid_referral(user_id)
    await callback.answer("Оплата отмечена ✅", show_alert=True)
    if ref_bonus:
        try:
            await bot.send_message(ref_bonus[0], f"💰 Твой друг оплатил Premium. +{REF_PAID_BONUS_DAYS} дней!\nPremium до: {ref_bonus[1]}")
        except Exception:
            pass
    await callback.message.edit_text(
        format_admin_user_card(user_id),
        reply_markup=user_detail_keyboard(user_id, page)
    )


@dp.callback_query(F.data == "admin_my_id")
async def admin_my_id_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        f"Твой Telegram ID:\n\n{callback.from_user.id}\n\nADMIN_ID сейчас:\n\n{ADMIN_ID}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data == "admin_give_premium")
async def admin_give_premium_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Чтобы выдать Premium вручную:\n\n/premium USER_ID\n\nИли открой 👥 Пользователи → карточка пользователя.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data == "admin_remove_premium")
async def admin_remove_premium_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Чтобы снять Premium вручную:\n\n/unpremium USER_ID\n\nИли открой 👥 Пользователи → карточка пользователя.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data == "admin_reset_limit")
async def admin_reset_limit_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Чтобы сбросить лимит вручную:\n\n/reset USER_ID\n\nИли открой 👥 Пользователи → карточка пользователя.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data == "admin_refs")
async def admin_refs_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT referrer_id, referred_id, registration_bonus_given, paid_bonus_given, created_at, paid_at FROM referrals ORDER BY id DESC LIMIT 30")
    rows = cur.fetchall()
    conn.close()
    await callback.answer()
    if not rows:
        text = "Рефералов пока нет."
    else:
        text = "👥 Рефералы:\n\n"
        for referrer_id, referred_id, reg_bonus, paid_bonus, created_at, paid_at in rows:
            text += f"Кто: {referrer_id}\nКого: {referred_id}\nРег.бонус: {reg_bonus}\nОплатил: {paid_bonus}\nДата: {created_at}\nОплата: {paid_at or '-'}\n\n"
        text = text[:3900]
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_home")]
        ])
    )


@dp.callback_query(F.data.startswith("user_premium:"))
async def user_premium_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    until = add_premium_days(user_id, DEFAULT_PREMIUM_DAYS)
    reset_requests(user_id)
    await callback.answer("Premium выдан ✅", show_alert=True)
    await callback.message.answer(f"Premium выдан пользователю {user_id} до {until}")
    try:
        await bot.send_message(user_id, f"🎉 Тебе выдали Premium на {DEFAULT_PREMIUM_DAYS} дней. Доступ до: {until}")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("user_unpremium:"))
async def user_unpremium_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    set_premium(user_id, 0)
    await callback.answer("Premium снят", show_alert=True)


@dp.callback_query(F.data.startswith("user_reset:"))
async def user_reset_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    reset_requests(user_id)
    await callback.answer("Лимит сброшен ✅", show_alert=True)


@dp.callback_query(F.data.startswith("user_paid:"))
async def user_paid_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    until = add_premium_days(user_id, DEFAULT_PREMIUM_DAYS)
    reset_requests(user_id)
    ref_bonus = process_paid_referral(user_id)
    await callback.answer("Оплата отмечена ✅", show_alert=True)
    text = f"Оплата отмечена. Premium {user_id} до {until}."
    if ref_bonus:
        text += f"\nРефереру {ref_bonus[0]} начислено +{REF_PAID_BONUS_DAYS} дней до {ref_bonus[1]}."
    await callback.message.answer(text)


@dp.callback_query(F.data == "user_ref")
async def user_ref_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "👥 Пригласи друга — получи бонус\n\n"
        f"За регистрацию друга: +{REF_REGISTRATION_BONUS_DAYS} день Premium\n"
        f"Если друг оплатит: +{REF_PAID_BONUS_DAYS} дней Premium\n\n"
        f"Твоя ссылка:\n{get_ref_link(callback.from_user.id)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ К Premium", callback_data="buy_premium_stars")],
        ])
    )


@dp.callback_query(F.data.in_({"support_card", "support_crypto", "support_tech", "support_question"}))
async def support_topic_callback(callback: CallbackQuery):
    topic = callback.data.replace("support_", "")
    set_support_state(callback.from_user.id, topic)
    await callback.answer()

    topic_title = SUPPORT_TOPICS.get(topic, topic)
    examples = {
        "card": "Хочу оплатить Premium картой на 1 месяц.",
        "crypto": "Хочу оплатить Premium криптой, удобно USDT TRC20.",
        "tech": "У меня проблема с ботом: ...",
        "question": "У меня вопрос: ...",
    }

    await callback.message.answer(
        f"{topic_title}\n\n"
        "Напиши сообщение для администратора одним следующим сообщением.\n\n"
        f"Пример:\n{examples.get(topic, 'Здравствуйте, хочу связаться с админом.')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="support_cancel")]
        ])
    )


@dp.callback_query(F.data == "support_cancel")
async def support_cancel_callback(callback: CallbackQuery):
    clear_support_state(callback.from_user.id)
    await callback.answer("Отменено", show_alert=True)
    try:
        await callback.message.edit_text("Обращение отменено ✅")
    except Exception:
        await callback.message.answer("Обращение отменено ✅")


@dp.callback_query(F.data.startswith("support_reply_hint:"))
async def support_reply_hint_callback(callback: CallbackQuery):
    if not is_admin_user(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = callback.data.split(":", 1)[1]
    await callback.answer()
    await callback.message.answer(f"Чтобы ответить пользователю, отправь:\n\n/reply {user_id} текст ответа")


@dp.message(Command("reply"))
async def reply_to_user_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer("У тебя нет доступа.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование:\n/reply USER_ID текст ответа")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("USER_ID должен быть числом.")
        return

    answer_text = parts[2].strip()
    try:
        await bot.send_message(user_id, f"📩 Ответ администратора:\n\n{answer_text}")
        await message.answer("Ответ отправлен ✅")
    except Exception as e:
        logger.error(f"Support reply error: {e}")
        await message.answer("Не смог отправить ответ. Возможно, пользователь не запускал бота или заблокировал его.")


@dp.message(Command("premium"))
async def premium_command_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer("Открываю Premium 👇", reply_markup=premium_keyboard())
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование:\n/premium USER_ID")
        return
    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("USER_ID должен быть числом.")
        return
    until = add_premium_days(user_id, DEFAULT_PREMIUM_DAYS)
    reset_requests(user_id)
    await message.answer(f"Premium выдан пользователю {user_id} до {until} ✅")


@dp.message(Command("unpremium"))
async def unpremium_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer("У тебя нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование:\n/unpremium USER_ID")
        return
    user_id = int(args[1])
    set_premium(user_id, 0)
    await message.answer(f"Premium снят у пользователя {user_id}.")


@dp.message(Command("reset"))
async def reset_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer("У тебя нет доступа.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование:\n/reset USER_ID")
        return
    user_id = int(args[1])
    reset_requests(user_id)
    await message.answer(f"Лимит бесплатных запросов сброшен пользователю {user_id} ✅")

@dp.message(Command("block"))
async def block_user_handler(message: Message):
    if not is_admin_user(message.from_user.id):
        return

    args = message.text.split()

    if len(args) < 2:
        await message.answer("Использование: /block USER_ID")
        return

    user_id = int(args[1])

    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO blocked_users (user_id) VALUES (?)",
            (user_id,)
        )
        conn.commit()

    await message.answer(f"Пользователь {user_id} заблокирован.")


@dp.message(Command("unblock"))
async def unblock_user_handler(message: Message):
    if not is_admin_user(message.from_user.id):
        return

    args = message.text.split()

    if len(args) < 2:
        await message.answer("Использование: /unblock USER_ID")
        return

    user_id = int(args[1])

    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM blocked_users WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()

    await message.answer(f"Пользователь {user_id} разблокирован.")


@dp.message(Command("blocked"))
async def blocked_users_handler(message: Message):
    if not is_admin_user(message.from_user.id):
        return

    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM blocked_users ORDER BY user_id")
        rows = cur.fetchall()

    if not rows:
        await message.answer("Список блокировок пуст.")
        return

    text = "Заблокированные:\n\n"
    text += "\n".join(str(row[0]) for row in rows)

    await message.answer(text)
@dp.message(Command("chatpremium"))
async def chat_premium_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer("У тебя нет доступа.")
        return
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эта команда нужна именно в группе/чате. Добавь бота в чат и напиши там: /chatpremium 30")
        return
    days = DEFAULT_PREMIUM_DAYS
    args = message.text.split()
    if len(args) >= 2:
        try:
            days = int(args[1])
        except ValueError:
            await message.answer("Количество дней должно быть числом. Пример: /chatpremium 30")
            return
    until = add_chat_premium_days(message.chat.id, message.chat.title or "Чат", days)
    await message.answer(f"👑 Premium выдан всему чату на {days} дней.\nАктивен до: {until}")


@dp.message(Command("unchatpremium"))
async def unchat_premium_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer("У тебя нет доступа.")
        return
    if message.chat.type == ChatType.PRIVATE:
        await message.answer("Эта команда нужна именно в группе/чате.")
        return
    remove_chat_premium(message.chat.id)
    await message.answer("Premium у этого чата снят.")


@dp.message(Command("chatstatus"))
async def chat_status_handler(message: Message):
    await track_user_and_chat(message)
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(f"Твой статус:\n\n{get_status_text(message.from_user.id)}")
        return
    until = get_chat_premium_until(message.chat.id)
    if until and until > datetime.now():
        await message.answer(f"👑 У этого чата Premium до {until.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        await message.answer("У этого чата нет Premium.")


@dp.message(Command("ref"))
async def ref_handler(message: Message):
    await track_user_and_chat(message)
    await message.answer(
        "👥 Пригласи друга — получи бонус\n\n"
        f"За регистрацию: +{REF_REGISTRATION_BONUS_DAYS} день Premium\n"
        f"За оплату друга: +{REF_PAID_BONUS_DAYS} дней Premium\n\n"
        f"Твоя ссылка:\n{get_ref_link(message.from_user.id)}",
        reply_markup=user_keyboard(),
    )


@dp.message(Command("memory"))
async def memory_handler(message: Message):
    await track_user_and_chat(message)
    memory = get_permanent_memory(message.chat.id, 30)
    await message.answer("🧠 Память этого чата:\n\n" + (memory or "Пока пусто. Напиши: Лилу, запомни ..."))


@dp.message(Command("remember"))
async def remember_handler(message: Message):
    await track_user_and_chat(message)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Напиши так:\n/remember важный факт")
        return
    remembered_text = parts[1].strip()
    save_permanent_memory(message, remembered_text)
    await message.answer(f"Запомнила ✅\n\n«{remembered_text}»")


@dp.message(Command("forget_chat_memory"))
async def forget_chat_memory_handler(message: Message):
    await track_user_and_chat(message)
    if not is_admin_user(message.from_user.id):
        await message.answer("Очистить память может только админ.")
        return
    clear_permanent_memory(message.chat.id)
    await message.answer("Память этого чата очищена ✅")


@dp.message(Command("forget_me"))
async def forget_me_handler(message: Message):
    await track_user_and_chat(message)

    user_id = message.from_user.id

    conn = db_connect()
    cur = conn.cursor()

    # В личке chat_id == user_id. В группах удаляем только сообщения этого пользователя.
    if message.chat.type == ChatType.PRIVATE:
        cur.execute("DELETE FROM chat_messages WHERE chat_id = ?", (message.chat.id,))
        cur.execute("DELETE FROM chat_memory WHERE chat_id = ?", (message.chat.id,))
    else:
        cur.execute("DELETE FROM chat_messages WHERE chat_id = ? AND user_id = ?", (message.chat.id, user_id))
        cur.execute("DELETE FROM chat_memory WHERE chat_id = ? AND user_id = ?", (message.chat.id, user_id))

    conn.commit()
    conn.close()

    await message.answer("Хорошо. Я забыла нашу переписку и сохранённую память по тебе ✅")


async def handle_user_menu(message: Message, text: str) -> bool:
    if message.chat.type != ChatType.PRIVATE:
        return False
    if text == "👤 Мой профиль":
        await try_delete_message(message)
        await message.answer(format_profile(message.from_user.id, message.from_user.first_name), reply_markup=user_keyboard())
        return True
    if text == "⭐ Premium":
        await try_delete_message(message)
        await message.answer(
            "⭐ Premium\n\n"
            f"Стоимость: {PREMIUM_STARS_PRICE} Telegram Stars\n"
            f"Срок: {DEFAULT_PREMIUM_DAYS} дней\n\n"
            "Что даёт:\n"
            "— больше общения с Lilu;\n"
            "— анализ скринов;\n"
            "— память диалога;\n"
            "— глубокие разборы переписок и отношений.",
            reply_markup=premium_keyboard(),
        )
        return True
    if text == "👥 Пригласить друга":
        await try_delete_message(message)
        await ref_handler(message)
        return True
    if text == "ℹ️ Помощь":
        await try_delete_message(message)
        await help_handler(message)
        return True
    if text == "💬 Общаться с Lilu":
        await try_delete_message(message)
        await message.answer("Я тут 💬 Просто напиши, что хочешь обсудить.", reply_markup=user_keyboard())
        return True
    return False


@dp.message(F.text)
async def text_handler(message: Message):
    if is_user_blocked(message.from_user.id):
        return
    await track_user_and_chat(message)
    text_original = message.text or ""
    save_chat_message(message, text_original, is_bot=0)

    remembered = extract_remember_text(text_original)
    if remembered:
        save_permanent_memory(message, remembered)
        await message.answer(f"Запомнила ✅\n\n«{remembered}»")
        return

    if await handle_user_menu(message, text_original.strip()):
        return

    support_topic = get_support_state(message.from_user.id) if message.chat.type == ChatType.PRIVATE else None
    if support_topic:
        await send_support_request_to_admin(message, support_topic, text_original)
        clear_support_state(message.from_user.id)
        await message.answer(
            "✅ Сообщение отправлено администратору. Ответ придёт сюда в бот.",
            reply_markup=user_keyboard()
        )
        return

    auto_reply = False
    if is_group_chat(message) and not should_answer_in_chat(message):
        if can_auto_reply(message.chat.id):
            auto_reply = True
        else:
            return

    user_id = message.from_user.id
    premium = has_premium_access(message)
    if not premium and get_user_requests(user_id) >= FREE_REQUEST_LIMIT:
        await message.answer(
            "Пробный доступ закончился. Чтобы продолжить — нужен Premium.",
            reply_markup=premium_keyboard() if message.chat.type == ChatType.PRIVATE else None,
        )
        return

    # Естественная генерация изображений без команды /photo:
    # «покажи как выглядишь», «нарисуй...», «сгенерируй картинку...»
    if is_image_generation_request(text_original):
        await handle_image_generation(message, text_original, premium)
        add_request(user_id)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    try:
        user_text = clean_group_text(text_original) if is_group_chat(message) else text_original
        chat_memory = get_chat_context(message.chat.id, CHAT_CONTEXT_LIMIT)
        human_memory = get_recent_human_context(message.chat.id, 12)
        permanent_memory = get_permanent_memory(message.chat.id, 30)
        chat_context = "Это групповой чат." if is_group_chat(message) else "Это личный чат."
        auto_note = "Ты не была упомянута напрямую, поддержи общий разговор коротко и уместно." if auto_reply else ""
        if is_chat_premium(message.chat.id) and not is_user_premium(user_id):
            premium_note = "У этого чата общий Premium. Пользователь может общаться без личного лимита."
        else:
            premium_note = "У пользователя Premium." if premium else "У пользователя пробный доступ."

        prompt = f"""
{chat_context}
{premium_note}
{auto_note}

ВАЖНО ПРО КОНТЕКСТ:
- Не начинай разговор заново, если тема уже есть в истории.
- Если пользователь пишет "она", "он", "это", "тот момент", "как продолжить", "а дальше?" — найди, к чему это относится в истории ниже.
- Сначала пойми последнюю тему диалога, потом отвечай.
- Если информации не хватает, задай один короткий уточняющий вопрос.
- Не пересказывай всю историю, а используй её молча.
- Не отвечай общими фразами, если в истории есть конкретная ситуация.

Постоянная память чата:
{permanent_memory or 'пусто'}

Последние сообщения людей:
{human_memory or 'пусто'}

Полная короткая история диалога:
{chat_memory or 'пусто'}

Последнее сообщение пользователя:
{user_text}

Ответь как Lilu AI.
Если это продолжение прошлой темы — продолжай именно её.
Если вопрос практический — дай конкретику, шаги и примеры.
Если это обычное общение — просто общайся.
Если это разбор переписки/отношений — учитывай всё, что уже обсуждали ранее.

Правила против зацикливания:
- не повторяй свой прошлый ответ;
- если похожая мысль уже была в истории, сформулируй иначе или задай новый вопрос;
- не копируй свои сообщения из истории;
- в группе не зацикливайся на одном нике, отвечай всему чату, если нет прямого обращения;
- если это автоответ без прямого обращения, не обращайся к одному человеку по имени, говори в общий чат.
"""
        answer = await asyncio.to_thread(
            grok_text_response,
            prompt,
            0.75,
            900,
        )

        last_bot_answer = get_last_bot_message(message.chat.id)
        if normalize_for_compare(answer) == normalize_for_compare(last_bot_answer):
            answer = "Не хочу повторяться 😄 Давайте лучше оттолкнёмся от последнего сообщения: что именно обсуждаем дальше?"

        add_request(user_id)
        if not premium and message.chat.type == ChatType.PRIVATE:
            answer += f"\n\nОсталось пробных запросов: {free_left(user_id)}/{FREE_REQUEST_LIMIT}"
        sent = await message.answer(answer, reply_markup=user_keyboard() if message.chat.type == ChatType.PRIVATE else None)
        save_chat_message(sent, answer, is_bot=1)
        if is_group_chat(message):
            mark_bot_replied(message.chat.id)
    except Exception:
        logger.exception("Grok error")
        await message.answer("Ошибка AI. Возможно, лимит xAI/Grok, неверный API-ключ или модель недоступна.")


@dp.message(F.photo)
async def photo_handler(message: Message):
    await track_user_and_chat(message)
    caption = message.caption or "[фото без подписи]"
    save_chat_message(message, caption, is_bot=0)
    if is_group_chat(message) and not should_answer_in_chat(message):
        return
    if not has_premium_access(message) and get_user_requests(message.from_user.id) >= FREE_REQUEST_LIMIT:
        await message.answer("Пробный доступ закончился. Чтобы анализировать скрины — нужен Premium.", reply_markup=premium_keyboard() if message.chat.type == ChatType.PRIVATE else None)
        return
    try:
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
        answer = await analyze_photo_with_grok(message, caption)
        add_request(message.from_user.id)
        sent = await message.answer(answer, reply_markup=user_keyboard() if message.chat.type == ChatType.PRIVATE else None)
        save_chat_message(sent, answer, is_bot=1)
        if is_group_chat(message):
            mark_bot_replied(message.chat.id)
    except Exception:
        logger.exception("Vision error")
        await message.answer("Не смогла разобрать фото. Попробуй прислать чётче.")


@dp.message()
async def unknown_handler(message: Message):
    await track_user_and_chat(message)
    if is_group_chat(message) and not should_answer_in_chat(message):
        return
    await message.answer("Напиши текстом, что хочешь обсудить.", reply_markup=user_keyboard() if message.chat.type == ChatType.PRIVATE else None)



async def initiative_loop():
    """Фоновая инициатива Lilu: сама продолжает тему после тишины.

    В личке пишет чаще, в группах осторожнее. Не отправляет второе инициативное
    сообщение подряд, пока человек снова не ответит.
    """
    await asyncio.sleep(20)

    while True:
        try:
            if not AUTO_INITIATIVE_ENABLED:
                await asyncio.sleep(AUTO_INITIATIVE_CHECK_INTERVAL_SECONDS)
                continue

            for chat_id, chat_type, title, _last_id in get_known_chats_for_initiative():
                if chat_type == "private" and is_user_blocked(chat_id):
                    continue

                if not should_send_initiative(chat_id, chat_type):
                    continue

                chat_memory = get_chat_context(chat_id, CHAT_CONTEXT_LIMIT)
                permanent_memory = get_permanent_memory(chat_id, 30)

                if chat_type in ("group", "supergroup"):
                    initiative_style = (
                        "Это групповой чат. Напиши одно короткое сообщение в общий чат."
                    )
                else:
                    initiative_style = (
                        "Это личный чат. Напиши одно короткое сообщение."
                    )

                prompt = f"""
Ты Lilu AI. Тебе нужно самой продолжить разговор после паузы.

{initiative_style}

Постоянная память:
{permanent_memory or 'пусто'}

Последняя история диалога:
{chat_memory or 'пусто'}

Правила:
- 1 короткое сообщение;
- не повторяй прошлые ответы;
- продолжай тему из истории, если она понятна;
- если тема непонятна — задай лёгкий вопрос;
- не начинай каждый раз одинаково;
- не пиши, что ты бот или что это автосообщение.
"""

                answer = await asyncio.to_thread(grok_text_response, prompt, 0.8, 350)
                if not answer:
                    continue

                last_bot_answer = get_last_bot_message(chat_id)
                if normalize_for_compare(answer) == normalize_for_compare(last_bot_answer):
                    continue

                await bot.send_message(chat_id, answer)
                save_bot_message_by_chat(chat_id, answer)

                if chat_type in ("group", "supergroup"):
                    mark_bot_replied(chat_id)

                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"initiative_loop error: {e}")

        await asyncio.sleep(AUTO_INITIATIVE_CHECK_INTERVAL_SECONDS)


async def main():
    global BOT_USERNAME, BOT_ID
    init_db()
    me = await bot.get_me()
    BOT_USERNAME = me.username
    BOT_ID = me.id
    logger.info(f"Lilu AI запущена | @{BOT_USERNAME} | Model: {XAI_MODEL} | Vision: {XAI_VISION_MODEL} | DB: {DB_PATH}")
    logger.info(f"Premium Stars price: {PREMIUM_STARS_PRICE}")
    logger.info(f"IMAGE_GENERATION_ENABLED: {IMAGE_GENERATION_ENABLED} | PROVIDER: {IMAGE_PROVIDER}")
    logger.info(f"AUTO_INITIATIVE_ENABLED: {AUTO_INITIATIVE_ENABLED}")
    logger.info(f"AUTO_INITIATIVE_PRIVATE_SILENCE_SECONDS: {AUTO_INITIATIVE_PRIVATE_SILENCE_SECONDS}")
    logger.info(f"AUTO_INITIATIVE_GROUP_SILENCE_SECONDS: {AUTO_INITIATIVE_GROUP_SILENCE_SECONDS}")

    asyncio.create_task(initiative_loop())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
