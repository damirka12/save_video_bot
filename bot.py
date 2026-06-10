import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, USE_LOCAL_SERVER, LOCAL_SERVER_URL
from handlers.start import router as start_router
from handlers.download import router as download_router
from handlers.admin import router as admin_router
from services.db_service import init_db
from services.downloader import cleanup_downloads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


async def main():
    await init_db()
    removed = cleanup_downloads()
    if removed:
        logging.info(f"Очищено сиротливых файлов: {removed}")

    if USE_LOCAL_SERVER:
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.client.telegram import TelegramAPIServer
        session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_SERVER_URL))
        bot = Bot(token=BOT_TOKEN, session=session)
        logging.info(f"Локальный Bot API сервер: {LOCAL_SERVER_URL} (лимит до 2000 МБ)")
        # Сервер поднимается на пару секунд дольше — ждём готовности
        for attempt in range(30):
            try:
                me = await bot.get_me()
                logging.info(f"Подключился к локальному серверу как @{me.username}")
                break
            except Exception as e:
                logging.warning(f"Жду локальный Bot API сервер... ({type(e).__name__})")
                await asyncio.sleep(2)
    else:
        bot = Bot(token=BOT_TOKEN)

    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(download_router)

    print("🤖 Save Video Bot запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
