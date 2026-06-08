"""
Funstat Bot — Asosiy handlerlar
Foydalanuvchilar bilan muloqot qiluvchi qism
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import (
    TelegramUser, BotUser, NameHistory, GroupMembership,
    TelegramGroup, UserMessage, TrackedUser, async_session
)
from collector.telegram_collector import (
    search_user_by_username, fetch_user_messages
)
from datetime import datetime
from loguru import logger
import os

router = Router()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]


class SearchState(StatesGroup):
    waiting_username = State()
    waiting_group = State()


# ─── YORDAMCHI FUNKSIYALAR ───────────────────────────────────────────

async def get_or_create_bot_user(session: AsyncSession, message: Message) -> BotUser:
    """Bot foydalanuvchisini olish yoki yaratish"""
    result = await session.execute(
        select(BotUser).where(BotUser.id == message.from_user.id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = BotUser(
            id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            is_admin=message.from_user.id in ADMIN_IDS,
            credits=5
        )
        session.add(user)
        await session.commit()
    return user


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Asosiy menyu"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Foydalanuvchi qidirish", callback_data="search_user"),
            InlineKeyboardButton(text="👥 Guruh qidirish", callback_data="search_group"),
        ],
        [
            InlineKeyboardButton(text="👁 Kuzatish", callback_data="track_user"),
            InlineKeyboardButton(text="📊 Statistika", callback_data="statistics"),
        ],
        [
            InlineKeyboardButton(text="💳 Kreditlar", callback_data="my_credits"),
            InlineKeyboardButton(text="❓ Yordam", callback_data="help"),
        ]
    ])


def user_result_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Foydalanuvchi natijasi uchun klaviatura"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Xabarlar tarixi", callback_data=f"messages_{user_id}"),
            InlineKeyboardButton(text="👥 Guruhlari", callback_data=f"groups_{user_id}"),
        ],
        [
            InlineKeyboardButton(text="🕒 Ism tarixi", callback_data=f"names_{user_id}"),
            InlineKeyboardButton(text="👁 Kuzatishni boshlash", callback_data=f"track_{user_id}"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")]
    ])


# ─── KOMANDALAR ──────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    async with async_session() as session:
        user = await get_or_create_bot_user(session, message)

    await message.answer(
        f"👋 Salom, <b>{message.from_user.first_name}</b>!\n\n"
        f"🤖 <b>Funstat Bot</b> — Telegram foydalanuvchilarini tahlil qiluvchi kuchli vosita.\n\n"
        f"💳 Sizda <b>{user.credits} ta</b> bepul so'rov bor.\n\n"
        f"Quyidagi tugmalardan birini tanlang 👇",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Funstat Bot — Yordam</b>\n\n"
        "<b>Buyruqlar:</b>\n"
        "• /start — Bosh menyu\n"
        "• /search @username — Foydalanuvchi qidirish\n"
        "• /group @guruh — Guruh tahlili\n"
        "• /track @username — Kuzatishni boshlash\n"
        "• /stats — Mening statistikam\n"
        "• /credits — Kreditlar holati\n\n"
        "<b>Imkoniyatlar:</b>\n"
        "🔍 Username bo'yicha qidirish\n"
        "📝 Xabarlar tarixini ko'rish\n"
        "👥 Foydalanuvchi guruhlarini ko'rish\n"
        "🕒 Ism o'zgarishlari tarixini ko'rish\n"
        "👁 Real vaqtda kuzatish",
        parse_mode="HTML"
    )


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) > 1:
        username = args[1].lstrip("@")
        await do_user_search(message, username)
    else:
        await message.answer(
            "🔍 <b>Qidirish</b>\n\nQidirmoqchi bo'lgan foydalanuvchi username'ini yuboring:\n"
            "Misol: <code>@username</code>",
            parse_mode="HTML"
        )
        await state.set_state(SearchState.waiting_username)


@router.message(SearchState.waiting_username)
async def process_username_search(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    await state.clear()
    await do_user_search(message, username)


async def do_user_search(message: Message, username: str):
    """Asosiy qidirish logikasi"""
    async with async_session() as session:
        bot_user = await get_or_create_bot_user(session, message)

        if bot_user.credits <= 0 and not bot_user.is_admin:
            await message.answer(
                "❌ <b>Kreditlar tugadi!</b>\n\n"
                "Yangi so'rovlar uchun kredit sotib oling.",
                parse_mode="HTML"
            )
            return

        wait_msg = await message.answer("⏳ <b>Izlanmoqda...</b>", parse_mode="HTML")

        # Avval bazadan qidirish
        result = await session.execute(
            select(TelegramUser).where(TelegramUser.username == username)
        )
        db_user = result.scalar_one_or_none()

        if db_user:
            # Bazadan topildi
            groups_count = await session.execute(
                select(func.count()).where(
                    GroupMembership.user_id == db_user.id,
                    GroupMembership.is_active == True
                )
            )
            g_count = groups_count.scalar()

            messages_count = await session.execute(
                select(func.count()).where(UserMessage.user_id == db_user.id)
            )
            m_count = messages_count.scalar()

            text = (
                f"✅ <b>Foydalanuvchi topildi!</b>\n\n"
                f"👤 <b>Ism:</b> {db_user.first_name or '—'} {db_user.last_name or ''}\n"
                f"🔖 <b>Username:</b> @{db_user.username or '—'}\n"
                f"🆔 <b>ID:</b> <code>{db_user.id}</code>\n"
                f"⭐ <b>Premium:</b> {'✅' if db_user.is_premium else '❌'}\n"
                f"👥 <b>Guruhlarda:</b> {g_count} ta\n"
                f"💬 <b>Xabarlar:</b> {m_count} ta\n"
                f"📅 <b>Birinchi ko'rilgan:</b> {db_user.first_seen.strftime('%d.%m.%Y')}\n"
            )

            # Kreditni kamaytirish
            if not bot_user.is_admin:
                bot_user.credits -= 1
                bot_user.total_searches += 1
                await session.commit()

            await wait_msg.edit_text(text, parse_mode="HTML",
                                      reply_markup=user_result_keyboard(db_user.id))

        else:
            # Telegram'dan qidirish
            user_info = await search_user_by_username(username)
            if user_info:
                text = (
                    f"🌐 <b>Telegram'dan topildi:</b>\n\n"
                    f"👤 <b>Ism:</b> {user_info.get('first_name') or '—'} {user_info.get('last_name') or ''}\n"
                    f"🔖 <b>Username:</b> @{user_info.get('username') or '—'}\n"
                    f"🆔 <b>ID:</b> <code>{user_info.get('id')}</code>\n"
                    f"⭐ <b>Premium:</b> {'✅' if user_info.get('is_premium') else '❌'}\n"
                    f"📝 <b>Bio:</b> {user_info.get('bio') or '—'}\n\n"
                    f"<i>⚠️ Tarix ma'lumotlari bazada yo'q — foydalanuvchi kuzatuvga qo'shilmagan.</i>"
                )

                if not bot_user.is_admin:
                    bot_user.credits -= 1
                    bot_user.total_searches += 1
                    await session.commit()

                await wait_msg.edit_text(text, parse_mode="HTML")
            else:
                await wait_msg.edit_text(
                    f"❌ <b>Foydalanuvchi topilmadi:</b> @{username}\n\n"
                    f"Username noto'g'ri yoki foydalanuvchi mavjud emas.",
                    parse_mode="HTML"
                )


@router.message(Command("track"))
async def cmd_track(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Misol: /track @username")
        return

    username = args[1].lstrip("@")
    async with async_session() as session:
        # Foydalanuvchini topish
        result = await session.execute(
            select(TelegramUser).where(TelegramUser.username == username)
        )
        target = result.scalar_one_or_none()

        if not target:
            await message.answer(f"❌ @{username} bazada topilmadi.\nAvval /search bilan qidiring.")
            return

        # Kuzatuvga qo'shish
        existing = await session.execute(
            select(TrackedUser).where(
                TrackedUser.tracker_bot_user_id == message.from_user.id,
                TrackedUser.tracked_telegram_id == target.id,
                TrackedUser.is_active == True
            )
        )
        if existing.scalar_one_or_none():
            await message.answer(f"ℹ️ @{username} allaqachon kuzatilmoqda.")
            return

        track = TrackedUser(
            tracker_bot_user_id=message.from_user.id,
            tracked_telegram_id=target.id
        )
        session.add(track)
        await session.commit()

    await message.answer(
        f"✅ <b>@{username} kuzatuvga qo'shildi!</b>\n\n"
        f"Ism, username yoki profil rasm o'zgarganda xabardor qilinasiz. 🔔",
        parse_mode="HTML"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    async with async_session() as session:
        users_count = await session.execute(select(func.count()).select_from(TelegramUser))
        groups_count = await session.execute(select(func.count()).select_from(TelegramGroup))
        messages_count = await session.execute(select(func.count()).select_from(UserMessage))

        await message.answer(
            "📊 <b>Funstat statistika:</b>\n\n"
            f"👤 Foydalanuvchilar: <b>{users_count.scalar():,}</b>\n"
            f"👥 Guruhlar: <b>{groups_count.scalar():,}</b>\n"
            f"💬 Xabarlar: <b>{messages_count.scalar():,}</b>",
            parse_mode="HTML"
        )


@router.message(Command("credits"))
async def cmd_credits(message: Message):
    async with async_session() as session:
        user = await get_or_create_bot_user(session, message)
        await message.answer(
            f"💳 <b>Sizning kreditlaringiz:</b> {user.credits} ta\n"
            f"📈 <b>Jami qidiruvlar:</b> {user.total_searches} ta\n\n"
            f"Har kuni 3 ta bepul kredit beriladi.",
            parse_mode="HTML"
        )


# ─── CALLBACK HANDLERLAR ─────────────────────────────────────────────

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏠 <b>Bosh menyu</b>\n\nNima qilmoqchisiz?",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


@router.callback_query(F.data == "search_user")
async def cb_search_user(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔍 <b>Foydalanuvchi qidirish</b>\n\n"
        "Username yuboring (@ bilan yoki usiz):",
        parse_mode="HTML"
    )
    await state.set_state(SearchState.waiting_username)
    await callback.answer()


@router.callback_query(F.data == "statistics")
async def cb_statistics(callback: CallbackQuery):
    async with async_session() as session:
        users_count = (await session.execute(select(func.count()).select_from(TelegramUser))).scalar()
        groups_count = (await session.execute(select(func.count()).select_from(TelegramGroup))).scalar()
        messages_count = (await session.execute(select(func.count()).select_from(UserMessage))).scalar()

    await callback.message.edit_text(
        "📊 <b>Baza statistikasi:</b>\n\n"
        f"👤 Foydalanuvchilar: <b>{users_count:,}</b>\n"
        f"👥 Guruhlar: <b>{groups_count:,}</b>\n"
        f"💬 Xabarlar: <b>{messages_count:,}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("names_"))
async def cb_name_history(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        result = await session.execute(
            select(NameHistory)
            .where(NameHistory.user_id == user_id)
            .order_by(desc(NameHistory.changed_at))
            .limit(10)
        )
        history = result.scalars().all()

    if not history:
        await callback.answer("Tarix topilmadi", show_alert=True)
        return

    text = "🕒 <b>Ism o'zgarishlari tarixi:</b>\n\n"
    for h in history:
        text += (
            f"📅 {h.changed_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"   Ism: {h.first_name or '—'} {h.last_name or ''}\n"
            f"   Username: @{h.username or '—'}\n\n"
        )

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("groups_"))
async def cb_user_groups(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        result = await session.execute(
            select(TelegramGroup)
            .join(GroupMembership, GroupMembership.group_id == TelegramGroup.id)
            .where(GroupMembership.user_id == user_id, GroupMembership.is_active == True)
            .limit(15)
        )
        groups = result.scalars().all()

    if not groups:
        await callback.answer("Guruhlar topilmadi", show_alert=True)
        return

    text = "👥 <b>Foydalanuvchi guruhlari:</b>\n\n"
    for g in groups:
        icon = "📢" if g.is_channel else "👥"
        link = f"@{g.username}" if g.username else f"ID: {g.id}"
        text += f"{icon} {g.title} ({link})\n"

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")]
        ])
    )
    await callback.answer()
