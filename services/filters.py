from aiogram.filters import Filter
from aiogram.types import Message

from services.texts import raw


class TextEquals(Filter):
    """Сравнивает текст сообщения с ТЕКУЩЕЙ подписью кнопки из реестра текстов.
    Благодаря этому подписи reply-кнопок можно менять в админке, не ломая хендлеры."""

    def __init__(self, key: str):
        self.key = key

    async def __call__(self, message: Message) -> bool:
        return bool(message.text) and message.text == await raw(self.key)
