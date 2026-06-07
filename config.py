import os

# ─── Telegram ────────────────────────────────────────────────
# Берётся из переменной окружения BOT_TOKEN (см. .env / docker-compose),
# с фолбэком на захардкоженное значение для локального запуска.
BOT_TOKEN = os.getenv("BOT_TOKEN") or "7554465775:AAE3x74_-jMdSjgMcEAl-0WbRbsZj18IV9Q"
ADMIN_ID  = int(os.getenv("ADMIN_ID") or 679951507)

# ─── Telegram Local Server ────────────────────────────────────
TELEGRAM_API_ID   = ""   # Получить на my.telegram.org
TELEGRAM_API_HASH = ""   # Получить на my.telegram.org
LOCAL_SERVER_URL  = "http://localhost:8081"
USE_LOCAL_SERVER  = False  # Поставь True после запуска сервера

# ─── Папка для скачивания ─────────────────────────────────────
DOWNLOAD_DIR = "downloads"

# ─── Лимит Telegram (МБ) ─────────────────────────────────────
TELEGRAM_LIMIT_MB = 2000 if USE_LOCAL_SERVER else 50
