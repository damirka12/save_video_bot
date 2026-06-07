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

# ─── Защита / лимиты ─────────────────────────────────────────
# Максимальная длина видео в секундах (0 — без лимита). Не качаем то, что заведомо не влезет.
MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION") or 3600)
# Сколько скачиваний может идти одновременно (защита CPU/диска).
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS") or 3)
# Время жизни ссылки в кэше (сек) и максимум записей — чтобы кэш не тёк.
URL_CACHE_TTL = int(os.getenv("URL_CACHE_TTL") or 3600)
URL_CACHE_MAX = int(os.getenv("URL_CACHE_MAX") or 1000)
