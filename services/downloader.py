import os
import re
import json
import asyncio
import yt_dlp
from config import DOWNLOAD_DIR

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def cleanup_downloads():
    """Удаляет файлы, оставшиеся в папке загрузок (например, после краша
    между скачиванием и отправкой). Вызывается при старте бота."""
    removed = 0
    for name in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
        except Exception:
            pass
    return removed

# Поддерживаемые платформы
PLATFORMS = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "instagram.com": "Instagram",
    "tiktok.com": "TikTok",
    "rutube.ru": "RuTube",
    "vk.com": "VK",
    "twitter.com": "Twitter",
    "x.com": "Twitter",
}


def detect_platform(url: str) -> str:
    for domain, name in PLATFORMS.items():
        if domain in url:
            return name
    return "Видео"


def get_platform_emoji(platform: str) -> str:
    emojis = {
        "YouTube": "🎬",
        "Instagram": "📸",
        "TikTok": "🎵",
        "RuTube": "🎥",
        "VK": "💙",
        "Twitter": "🐦",
    }
    return emojis.get(platform, "🎬")


async def get_video_formats(url: str) -> list[dict]:
    """Получает доступные форматы без скачивания."""
    def sync_info():
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(sync_info)
        formats = []
        seen_heights = set()

        for f in info.get("formats", []):
            height = f.get("height")
            if height and height not in seen_heights and f.get("vcodec") != "none":
                seen_heights.add(height)
                size = f.get("filesize") or f.get("filesize_approx") or 0
                formats.append({
                    "format_id": f["format_id"],
                    "height": height,
                    "ext": f.get("ext", "mp4"),
                    "size_mb": round(size / 1024 / 1024, 1) if size else 0,
                })

        formats.sort(key=lambda x: x["height"], reverse=True)

        return {
            "title": info.get("title", "Видео"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", ""),
            "formats": formats[:5],  # Максимум 5 вариантов
        }
    except Exception as e:
        raise Exception(f"Не удалось получить информацию: {e}")


async def download_video(url: str, quality: str = "best", progress_cb=None, platform: str = "") -> dict:
    result = {}
    loop = asyncio.get_event_loop()
    simple = platform in ("TikTok", "Instagram")

    def sync_download():
        if quality == "audio":
            fmt = "bestaudio/best"
        elif simple:
            # Скачиваем уже готовый файл без склейки — так сохраняется оригинальный 9:16
            fmt = "best[ext=mp4]/best"
        elif quality == "360":
            fmt = "bestvideo[height<=360]+bestaudio/best[height<=360]"
        elif quality == "720":
            fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]"
        elif quality == "1080":
            fmt = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        else:
            fmt = "best[filesize<50M]/best"

        ydl_opts = {
            "format": fmt,
            "outtmpl": f"{DOWNLOAD_DIR}/%(title).50s.%(ext)s",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [lambda d: _hook(d, progress_cb, loop)],
            "extractor_args": {"youtube": {"player_client": ["ios"]}},
            "cookiefile": "youtube_cookies.txt" if os.path.exists("youtube_cookies.txt") else None,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if not os.path.exists(filepath):
                filepath = filepath.rsplit(".", 1)[0] + ".mp4"

            result["title"] = info.get("title", "Видео")
            result["filepath"] = filepath
            result["filesize"] = os.path.getsize(filepath) if os.path.exists(filepath) else 0
            result["duration"] = info.get("duration", 0)
            result["ext"] = "mp3" if quality == "audio" else "mp4"

    await asyncio.to_thread(sync_download)

    if simple and quality != "audio" and result.get("filepath"):
        result["filepath"] = await crop_portrait(result["filepath"])
        if os.path.exists(result["filepath"]):
            result["filesize"] = os.path.getsize(result["filepath"])

    return result


async def crop_portrait(filepath: str) -> str:
    import subprocess, json

    probe = await asyncio.to_thread(
        subprocess.run,
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,sample_aspect_ratio",
         "-of", "json", filepath],
        capture_output=True, text=True
    )
    try:
        stream = json.loads(probe.stdout)["streams"][0]
        w = stream["width"]
        h = stream["height"]
        sar = stream.get("sample_aspect_ratio", "1:1")
    except Exception:
        return filepath

    # Вычисляем реальные размеры с учётом SAR
    try:
        sar_n, sar_d = map(int, sar.split(":"))
        if sar_d == 0:
            sar_n, sar_d = 1, 1
    except Exception:
        sar_n, sar_d = 1, 1

    display_w = w * sar_n // sar_d
    display_h = h

    output = filepath.rsplit(".", 1)[0] + "_p.mp4"

    if display_h > display_w:
        # Портретный с кривым SAR — исправляем (нужен ре-encode чтобы применить фильтр)
        r = await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-i", filepath, "-vf", "setsar=1", "-preset", "veryfast", "-c:a", "copy", "-y", output],
            capture_output=True
        )
        if r.returncode == 0 and os.path.exists(output):
            os.remove(filepath)
            return output
        return filepath

    # Квадрат или пейзаж — cropdetect с повышенным порогом
    detect = await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-i", filepath, "-vf", "cropdetect=24:2:0",
         "-frames:v", "300", "-f", "null", "-"],
        capture_output=True, text=True
    )
    crops = re.findall(r"crop=(\d+:\d+:\d+:\d+)", detect.stderr)
    crop = None
    if crops:
        best = max(set(crops), key=crops.count)
        cw, ch = map(int, best.split(":")[:2])
        if ch > cw:  # принимаем только если результат портретный
            crop = best

    if not crop:
        # Принудительный центральный crop до 9:16
        cw = int(h * 9 / 16) & ~1
        cx = (w - cw) // 2
        crop = f"{cw}:{h}:{cx}:0"

    r = await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-i", filepath, "-vf", f"crop={crop}", "-preset", "veryfast", "-c:a", "copy", "-y", output],
        capture_output=True
    )
    if r.returncode == 0 and os.path.exists(output):
        os.remove(filepath)
        return output
    return filepath


async def compress_video(filepath: str, max_mb: int) -> str | None:
    import subprocess, json
    output = filepath.rsplit(".", 1)[0] + "_c.mp4"
    try:
        probe = await asyncio.to_thread(
            subprocess.run,
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            capture_output=True, text=True
        )
        duration = float(json.loads(probe.stdout)["format"]["duration"])
    except Exception:
        return None

    audio_kbps = 96
    video_kbps = int((max_mb * 8192) / duration * 0.90) - audio_kbps
    if video_kbps < 80:
        return None

    try:
        r = await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-i", filepath,
             "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{video_kbps}k",
             "-c:a", "aac", "-b:a", f"{audio_kbps}k",
             "-y", output],
            capture_output=True
        )
        if r.returncode == 0 and os.path.exists(output):
            return output
    except Exception:
        pass
    return None


def _hook(d: dict, callback, loop):
    if d["status"] == "downloading" and callback:
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        downloaded = d.get("downloaded_bytes", 0)
        if total:
            percent = int(downloaded / total * 100)
            asyncio.run_coroutine_threadsafe(callback(percent), loop)


def format_duration(seconds: int) -> str:
    if not seconds:
        return ""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def format_size(size_bytes: int) -> str:
    if size_bytes > 1024 ** 3:
        return f"{size_bytes / 1024**3:.1f} ГБ"
    return f"{size_bytes / 1024**2:.0f} МБ"
