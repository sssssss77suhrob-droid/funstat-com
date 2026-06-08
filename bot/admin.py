"""
Admin panel — bot adminlari uchun maxsus buyruqlar
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, func
from database.models import (
    TelegramUser, BotUser, TelegramGroup, UserMessage, async_session
)
from collector.telegram_collector import scan_group
from loguru import logger
import os

admin_router = Router()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@admin_router.message(Command("admin"))
async def cmd_admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with async_session() as session:
        users = (await session.execute(select(func.count()).select_from(TelegramUser))).scalar()
        bot_users = (await session.execute(select(func.count()).select_from(BotUser))).scalar()
        groups = (await session.execute(select(func.count()).select_from(TelegramGroup))).scalar()
        messages = (await session.execute(select(func.count()).select_from(UserMessage))).scalar()

    await message.answer(
        "🛡 <b>Admin Panel</b>\n\n"
        f"📊 <b>Baza holati:</b>\n"
        f"• TG foydalanuvchilar: {users:,}\n"
        f"• Bot foydalanuvchilar: {bot_users:,}\n"
        f"• Guruhlar: {groups:,}\n"
        f"• Xabarlar: {messages:,}\n\n"
        f"<b>Buyruqlar:</b>\n"
        f"/scan @guruh — Guruhni skanerlash\n"
        f"/ban user_id — Bloklash\n"
        f"/addcredits user_id miqdor — Kredit qo'shish\n"
        f"/broadcast — Hammaga xabar yuborish",
        parse_mode="HTML"
    )


@admin_router.message(Command("scan"))
async def cmd_scan_group(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Misol: /scan @guruh_nomi")
        return

    group_username = args[1]
    await message.answer(f"⏳ <b>{group_username}</b> skanerlash boshlandi...")

    try:
        await scan_group(group_username)
        await message.answer(f"✅ <b>{group_username}</b> muvaffaqiyatli skanerlandi!")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


@admin_router.message(Command("ban"))
async def cmd_ban_user(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Misol: /ban 123456789")
        return

    try:
        user_id = int(args[1])
        async with async_session() as session:
            result = await session.execute(select(BotUser).where(BotUser.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.is_banned = True
                await session.commit()
                await message.answer(f"✅ Foydalanuvchi {user_id} bloklandi.")
            else:
                await message.answer("❌ Foydalanuvchi topilmadi.")
    except ValueError:
        await message.answer("❌ Noto'g'ri ID format.")


@admin_router.message(Command("addcredits"))
async def cmd_add_credits(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer("Misol: /addcredits 123456789 50")
        return

    try:
        user_id = int(args[1])
        amount = int(args[2])
        async with async_session() as session:
            result = await session.execute(select(BotUser).where(BotUser.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.credits += amount
                await session.commit()
                await message.answer(f"✅ {user_id} ga {amount} kredit qo'shildi. Jami: {user.credits}")
            else:
                await message.answer("❌ Foydalanuvchi topilmadi.")
    except ValueError:
        await message.answer("❌ Noto'g'ri format.")
