from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from services.db_service import add_user
from services.texts import txt, raw
from services.filters import TextEquals
from config import ADMIN_ID

router = Router()


async def main_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=await raw("btn.help"))]]
    if is_admin:
        rows.append([KeyboardButton(text=await raw("btn.stats"))])
        rows.append([KeyboardButton(text=await raw("btn.broadcast"))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(Command("start"))
async def cmd_start(message: Message):
    await add_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await message.answer(
        await txt(
            "start.greeting",
            first_name=message.from_user.first_name,
            supported=await raw("common.supported"),
        ),
        parse_mode="HTML",
        reply_markup=await main_keyboard(message.from_user.id == ADMIN_ID),
    )


@router.message(Command("help"))
@router.message(TextEquals("btn.help"))
async def cmd_help(message: Message):
    await message.answer(
        await txt("help.text", supported=await raw("common.supported")),
        parse_mode="HTML",
    )
