import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from services.downloader import (
    download_video, detect_platform, get_platform_emoji,
    get_video_formats, format_duration, format_size, compress_video
)
from services.db_service import add_user
from services.texts import txt, raw
from config import TELEGRAM_LIMIT_MB

router = Router()

# Кэш URL для callback
_url_cache: dict[str, str] = {}


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
    _url_cache[url_key] = url

    label = await raw("dl.choose_format") if platform in SIMPLE_PLATFORMS else await raw("dl.choose_quality")

    try:
        info = await get_video_formats(url)
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

    quality_labels = {
        "360": "360p",
        "720": "720p",
        "1080": "1080p",
        "audio": "аудио",
        "best": "авто",
    }

    await callback.answer()
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
