"""Центральный реестр всех текстов бота.

Дефолты лежат здесь, переопределения — в БД (таблица texts), правятся через
веб-админку. Бот читает тексты через txt()/raw() с кэшем на _TTL секунд,
поэтому правки из админки подхватываются без перезапуска.
"""
import time
from string import Formatter

from services import db_service

# key         — уникальный идентификатор
# group       — раздел в админке
# label       — человекочитаемое название
# placeholders— какие {переменные} можно использовать в тексте
# default     — значение по умолчанию
REGISTRY = [
    # ── Старт / помощь ──
    {"key": "start.greeting", "group": "Старт и помощь", "label": "Приветствие (/start)",
     "placeholders": ["first_name", "supported"],
     "default": ("👋 Привет, <b>{first_name}</b>!\n\n"
                 "Я скачиваю видео из:\n\n"
                 "{supported}\n"
                 "Просто отправь ссылку — я всё сделаю! 👇")},
    {"key": "common.supported", "group": "Старт и помощь", "label": "Список поддерживаемых платформ",
     "placeholders": [],
     "default": ("🎬 <b>YouTube</b>\n"
                 "📸 <b>Instagram</b> (Reels, посты)\n"
                 "🎵 <b>TikTok</b>\n"
                 "🎥 <b>RuTube</b>\n"
                 "💙 <b>VK</b> (видео)\n")},
    {"key": "help.text", "group": "Старт и помощь", "label": "Как пользоваться (/help)",
     "placeholders": ["supported"],
     "default": ("📖 <b>Как пользоваться:</b>\n\n"
                 "1️⃣ Скопируй ссылку на видео\n"
                 "2️⃣ Отправь её мне\n"
                 "3️⃣ Выбери качество\n"
                 "4️⃣ Получи видео! 🎉\n\n"
                 "<b>Поддерживаемые платформы:</b>\n"
                 "{supported}")},

    # ── Reply-кнопки (нижняя клавиатура) ──
    {"key": "btn.help", "group": "Кнопки меню", "label": "Кнопка «Как пользоваться»",
     "placeholders": [], "default": "📥 Как пользоваться"},
    {"key": "btn.stats", "group": "Кнопки меню", "label": "Кнопка «Статистика» (админ)",
     "placeholders": [], "default": "📊 Статистика"},
    {"key": "btn.broadcast", "group": "Кнопки меню", "label": "Кнопка «Рассылка» (админ)",
     "placeholders": [], "default": "📢 Рассылка"},

    # ── Inline-кнопки выбора качества ──
    {"key": "btn.q.video", "group": "Кнопки качества", "label": "Кнопка «Видео»",
     "placeholders": [], "default": "🎬 Видео"},
    {"key": "btn.q.audio", "group": "Кнопки качества", "label": "Кнопка «Только аудио»",
     "placeholders": [], "default": "🎵 Только аудио"},
    {"key": "btn.q.360", "group": "Кнопки качества", "label": "Кнопка «360p»",
     "placeholders": [], "default": "📱 360p"},
    {"key": "btn.q.720", "group": "Кнопки качества", "label": "Кнопка «720p»",
     "placeholders": [], "default": "📺 720p"},
    {"key": "btn.q.1080", "group": "Кнопки качества", "label": "Кнопка «1080p»",
     "placeholders": [], "default": "🎬 1080p"},

    # ── Скачивание ──
    {"key": "dl.processing", "group": "Скачивание", "label": "Обработка ссылки",
     "placeholders": ["emoji", "platform"],
     "default": "{emoji} Обрабатываю ссылку с <b>{platform}</b>..."},
    {"key": "dl.choose_format", "group": "Скачивание", "label": "Подпись «Выбери формат» (TikTok/IG)",
     "placeholders": [], "default": "Выбери формат:"},
    {"key": "dl.choose_quality", "group": "Скачивание", "label": "Подпись «Выбери качество»",
     "placeholders": [], "default": "Выбери качество:"},
    {"key": "dl.info_simple", "group": "Скачивание", "label": "Карточка видео (TikTok/IG)",
     "placeholders": ["emoji", "platform", "label"],
     "default": "{emoji} <b>{platform}</b>\n\n{label}"},
    {"key": "dl.info_full", "group": "Скачивание", "label": "Карточка видео (с названием)",
     "placeholders": ["emoji", "title", "duration_line", "label"],
     "default": "{emoji} <b>{title}</b>\n{duration_line}\n\n{label}"},
    {"key": "dl.link_expired", "group": "Скачивание", "label": "Ссылка устарела",
     "placeholders": [], "default": "❌ Ссылка устарела, отправь снова"},
    {"key": "dl.too_long", "group": "Скачивание", "label": "Видео слишком длинное",
     "placeholders": ["duration", "limit"],
     "default": ("⏱ Видео слишком длинное ({duration})\n"
                 "Максимум — {limit}.\n"
                 "Попробуй видео покороче 🙏")},
    {"key": "dl.in_progress", "group": "Скачивание", "label": "У юзера уже идёт загрузка",
     "placeholders": [],
     "default": "⏳ Я ещё качаю твоё прошлое видео — дождись окончания, пожалуйста."},
    {"key": "dl.queued", "group": "Скачивание", "label": "Очередь (много загрузок)",
     "placeholders": [],
     "default": "⏳ Сейчас много загрузок — ты в очереди, подожди немного..."},
    {"key": "dl.downloading", "group": "Скачивание", "label": "Начало скачивания",
     "placeholders": ["quality"],
     "default": "⬇️ Скачиваю в качестве <b>{quality}</b>...\n\n⏳ Это может занять минуту"},
    {"key": "dl.progress", "group": "Скачивание", "label": "Прогресс скачивания",
     "placeholders": ["bar", "percent"],
     "default": "⬇️ Скачиваю...\n[{bar}] {percent}%"},
    {"key": "dl.error_download", "group": "Скачивание", "label": "Ошибка скачивания",
     "placeholders": ["error"],
     "default": "❌ Ошибка при скачивании:\n<code>{error}</code>"},
    {"key": "dl.not_found", "group": "Скачивание", "label": "Файл не найден",
     "placeholders": [], "default": "❌ Файл не найден после скачивания"},
    {"key": "dl.compressing", "group": "Скачивание", "label": "Сжатие большого файла",
     "placeholders": ["size", "limit"],
     "default": "📦 Файл большой ({size}), сжимаю до {limit} МБ..."},
    {"key": "dl.too_big", "group": "Скачивание", "label": "Файл слишком большой",
     "placeholders": ["size", "limit"],
     "default": ("⚠️ Файл слишком большой: <b>{size}</b>\n"
                 "Не удалось сжать до {limit} МБ\n\n"
                 "Попробуй выбрать качество пониже 👇")},
    {"key": "dl.uploading", "group": "Скачивание", "label": "Загрузка в Telegram",
     "placeholders": [], "default": "📤 Загружаю в Telegram..."},
    {"key": "dl.caption", "group": "Скачивание", "label": "Подпись под отправленным видео",
     "placeholders": [], "default": "@SaveVideoFreee_bot"},
    {"key": "dl.error_send", "group": "Скачивание", "label": "Ошибка отправки",
     "placeholders": ["error"],
     "default": "❌ Ошибка при отправке:\n<code>{error}</code>"},

    # ── Админ ──
    {"key": "admin.not_admin", "group": "Админ", "label": "Доступ только для админа",
     "placeholders": [], "default": "⛔ Только для администратора"},
    {"key": "admin.stats", "group": "Админ", "label": "Текст статистики",
     "placeholders": ["total", "today", "week"],
     "default": ("📊 <b>Статистика бота:</b>\n\n"
                 "👥 Всего пользователей: <b>{total}</b>\n"
                 "📅 Активны сегодня: <b>{today}</b>\n"
                 "📆 Активны за 7 дней: <b>{week}</b>")},
    {"key": "admin.broadcast_prompt", "group": "Админ", "label": "Запрос текста рассылки",
     "placeholders": ["total"],
     "default": ("📢 Отправь сообщение для рассылки\n"
                 "👥 Получат: <b>{total}</b> пользователей\n\n"
                 "/cancel — отменить")},
    {"key": "admin.cancel", "group": "Админ", "label": "Отмена",
     "placeholders": [], "default": "❌ Отменено"},
    {"key": "admin.broadcast_start", "group": "Админ", "label": "Старт рассылки",
     "placeholders": ["total"], "default": "📤 Рассылка на {total} пользователей..."},
    {"key": "admin.broadcast_progress", "group": "Админ", "label": "Прогресс рассылки",
     "placeholders": ["bar", "i", "total"], "default": "📤 [{bar}] {i}/{total}"},
    {"key": "admin.broadcast_done", "group": "Админ", "label": "Рассылка завершена",
     "placeholders": ["success", "failed"],
     "default": ("✅ <b>Рассылка завершена!</b>\n\n"
                 "✅ Доставлено: {success}\n"
                 "❌ Не доставлено: {failed}")},
]

DEFAULTS = {e["key"]: e["default"] for e in REGISTRY}

_TTL = 5.0
_cache: dict | None = None
_cache_ts = 0.0


class _SafeDict(dict):
    """Не падаем, если в шаблоне есть/нет лишних {плейсхолдеров}."""
    def __missing__(self, key):
        return "{" + key + "}"


def _render(template: str, kwargs: dict) -> str:
    if not kwargs:
        return template
    try:
        return Formatter().vformat(template, (), _SafeDict(kwargs))
    except Exception:
        return template


async def _load() -> dict:
    global _cache, _cache_ts
    overrides = await db_service.get_text_overrides()
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in overrides.items() if k in DEFAULTS})
    _cache = merged
    _cache_ts = time.monotonic()
    return merged


async def _all() -> dict:
    if _cache is None or (time.monotonic() - _cache_ts) > _TTL:
        return await _load()
    return _cache


async def raw(key: str) -> str:
    """Текст без подстановки (для кнопок и фильтров)."""
    data = await _all()
    return data.get(key, DEFAULTS.get(key, ""))


async def txt(key: str, **kwargs) -> str:
    """Текст с подстановкой {плейсхолдеров}."""
    return _render(await raw(key), kwargs)
