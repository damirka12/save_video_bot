import asyncio
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.db_service import get_stats, get_all_users
from services.texts import txt
from services.filters import TextEquals
from config import ADMIN_ID

router = Router()


class BroadcastState(StatesGroup):
    waiting = State()


@router.message(Command("stats"))
@router.message(TextEquals("btn.stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(await txt("admin.not_admin"))
        return

    stats = await get_stats()
    await message.answer(
        await txt("admin.stats", total=stats["total"], today=stats["today"], week=stats["week"]),
        parse_mode="HTML",
    )


@router.message(Command("broadcast"))
@router.message(TextEquals("btn.broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    stats = await get_stats()
    await state.set_state(BroadcastState.waiting)
    await message.answer(
        await txt("admin.broadcast_prompt", total=stats["total"]),
        parse_mode="HTML",
    )


@router.message(Command("cancel"), BroadcastState.waiting)
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(await txt("admin.cancel"))


@router.message(BroadcastState.waiting)
async def do_broadcast(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    users = await get_all_users()
    total = len(users)
    status = await message.answer(await txt("admin.broadcast_start", total=total))

    success, failed = 0, 0
    for i, user_id in enumerate(users):
        try:
            await message.copy_to(user_id)
            success += 1
        except Exception:
            failed += 1
        if (i + 1) % 20 == 0:
            try:
                bar = "▓" * int((i + 1) / total * 10) + "░" * (10 - int((i + 1) / total * 10))
                await status.edit_text(await txt("admin.broadcast_progress", bar=bar, i=i + 1, total=total))
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await status.edit_text(
        await txt("admin.broadcast_done", success=success, failed=failed),
        parse_mode="HTML",
    )
