import os
import time
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from services.downloader import (
    download_video, detect_platform, get_platform_emoji,
    get_video_formats, format_duration, format_size, compress_video
)
from services.db_service import add_user
from services.texts import txt, raw
from config import (
    TELEGRAM_LIMIT_MB, MAX_VIDEO_DURATION, MAX_CONCURRENT_DOWNLOADS,
    URL_CACHE_TTL, URL_CACHE_MAX,
)

router = Router()


class _TTLCache:
    """Кэш ссылок с временем жизни и ограничением размера — чтобы не тёк по памяти."""

    def __init__(self, ttl: int, maxsize: int):
        self.ttl = ttl
        self.maxsize = maxsize
        self._d: dict[str, tuple[str, float]] = {}

    def _evict(self):
        now = time.monotonic()
        for k in [k for k, (_, ts) in self._d.items() if now - ts > self.ttl]:
            del self._d[k]
        while len(self._d) > self.maxsize:
            oldest = min(self._d, key=lambda k: self._d[k][1])
            del self._d[oldest]

    def set(self, key: str, value: str):
        self._d[key] = (value, time.monotonic())
        self._evict()

    def get(self, key: str):
        item = self._d.get(key)
        if not item:
            return None
        value, ts = item
        if time.monotonic() - ts > self.ttl:
            del self._d[key]
            return None
        return value


# Кэш URL для callback (TTL + лимит размера)
_url_cache = _TTLCache(URL_CACHE_TTL, URL_CACHE_MAX)

# Защита: не больше N одновременных загрузок на весь бот + не больше 1 на юзера
_download_sem = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
_active_users: set[int] = set()


SIMPLE_PLATFORMS = {"TikTok", "Instagram"}


async def quality_keyboard(url_key: str, platform: str = "") -> InlineKeyboardMarkup:
    if platform in SIMPLE_PLATFORMS:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=await raw("btn.q.video"), callback_data=f"q:{url_key}:best"),
                InlineKeyboardButton(text=await raw("btn.q.audio"), callback_data=f"q:{url_key}:audio"),
            ],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=await raw("btn.q.360"), callback_data=f"q:{url_key}:360"),
            InlineKeyboardButton(text=await raw("btn.q.720"), callback_data=f"q:{url_key}:720"),
        ],
        [
            InlineKeyboardButton(text=await raw("btn.q.1080"), callback_data=f"q:{url_key}:1080"),
            InlineKeyboardButton(text=await raw("btn.q.audio"), callback_data=f"q:{url_key}:audio"),
        ],
    ])


@router.message(F.text.regexp(r'https?://'))
async def handle_url(message: Message):
    await add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    url = message.text.strip()
    platform = detect_platform(url)
    emoji = get_platform_emoji(platform)

    status = await message.answer(
        await txt("dl.processing", emoji=emoji, platform=platform),
        parse_mode="HTML"
    )

    # Сохраняем URL в кэш
    url_key = str(abs(hash(url)) % 10**9)
    _url_cache.set(url_key, url)

    label = await raw("dl.choose_format") if platform in SIMPLE_PLATFORMS else await raw("dl.choose_quality")

    try:
        info = await get_video_formats(url)

        # Пре-проверка длины — не качаем заведомо неподъёмное
        if MAX_VIDEO_DURATION and info["duration"] and info["duration"] > MAX_VIDEO_DURATION:
            await status.edit_text(
                await txt(
                    "dl.too_long",
                    duration=format_duration(info["duration"]),
                    limit=format_duration(MAX_VIDEO_DURATION),
                ),
                parse_mode="HTML",
            )
            return

        duration = format_duration(info["duration"])

        if platform in SIMPLE_PLATFORMS:
            text = await txt("dl.info_simple", emoji=emoji, platform=platform, label=label)
        else:
            duration_line = ("⏱ " + duration) if duration else ""
            text = await txt(
                "dl.info_full",
                emoji=emoji, title=info["title"][:60],
                duration_line=duration_line, label=label,
            )

        await status.edit_text(text, parse_mode="HTML", reply_markup=await quality_keyboard(url_key, platform))
    except Exception:
        await status.edit_text(
            await txt("dl.info_simple", emoji=emoji, platform=platform, label=label),
            parse_mode="HTML",
            reply_markup=await quality_keyboard(url_key, platform)
        )


@router.callback_query(F.data.startswith("q:"))
async def download_selected(callback: CallbackQuery):
    _, url_key, quality = callback.data.split(":")
    url = _url_cache.get(url_key)
    platform = detect_platform(url) if url else ""

    if not url:
        await callback.answer(await raw("dl.link_expired"), show_alert=True)
        return

    # Один юзер — одна загрузка за раз
    user_id = callback.from_user.id
    if user_id in _active_users:
        await callback.answer(await raw("dl.in_progress"), show_alert=True)
        return

    await callback.answer()
    _active_users.add(user_id)
    try:
        # Если все слоты заняты — честно предупреждаем, что ждём очередь
        if _download_sem.locked():
            await callback.message.edit_text(await txt("dl.queued"))
        async with _download_sem:
            await _do_download(callback, url, url_key, quality, platform)
    finally:
        _active_users.discard(user_id)


async def _do_download(callback: CallbackQuery, url: str, url_key: str, quality: str, platform: str):
    quality_labels = {
        "360": "360p",
        "720": "720p",
        "1080": "1080p",
        "audio": "аудио",
        "best": "авто",
    }

    await callback.message.edit_text(
        await txt("dl.downloading", quality=quality_labels.get(quality, quality)),
        parse_mode="HTML"
    )

    last_percent = [-1]

    async def update_progress(percent: int):
        if percent - last_percent[0] >= 15:
            last_percent[0] = percent
            bar = "▓" * (percent // 10) + "░" * (10 - percent // 10)
            try:
                await callback.message.edit_text(
                    await txt("dl.progress", bar=bar, percent=percent),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    try:
        result = await download_video(url, quality=quality, progress_cb=update_progress, platform=platform)
    except Exception as e:
        await callback.message.edit_text(
            await txt("dl.error_download", error=e),
            parse_mode="HTML"
        )
        return

    filepath = result["filepath"]
    filesize = result["filesize"]

    if not os.path.exists(filepath):
        await callback.message.edit_text(await txt("dl.not_found"))
        return

    compressed_path = None
    if filesize > TELEGRAM_LIMIT_MB * 1024 * 1024:
        await callback.message.edit_text(
            await txt("dl.compressing", size=format_size(filesize), limit=TELEGRAM_LIMIT_MB),
            parse_mode="HTML"
        )
        compressed_path = await compress_video(filepath, TELEGRAM_LIMIT_MB)
        if compressed_path and os.path.getsize(compressed_path) <= TELEGRAM_LIMIT_MB * 1024 * 1024:
            filepath = compressed_path
            filesize = os.path.getsize(filepath)
        else:
            if compressed_path and os.path.exists(compressed_path):
                os.remove(compressed_path)
            await callback.message.edit_text(
                await txt("dl.too_big", size=format_size(filesize), limit=TELEGRAM_LIMIT_MB),
                parse_mode="HTML",
                reply_markup=await quality_keyboard(url_key, platform)
            )
            return

    await callback.message.edit_text(await txt("dl.uploading"))

    try:
        from aiogram.types import FSInputFile
        caption = await raw("dl.caption")

        if quality == "audio":
            await callback.message.answer_audio(
                FSInputFile(filepath),
                caption=caption,
                parse_mode="HTML"
            )
        else:
            await callback.message.answer_video(
                FSInputFile(filepath),
                caption=caption,
                parse_mode="HTML"
            )

        await callback.message.delete()

    except Exception as e:
        await callback.message.edit_text(
            await txt("dl.error_send", error=e),
            parse_mode="HTML"
        )
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
        if compressed_path and os.path.exists(compressed_path):
            os.remove(compressed_path)
