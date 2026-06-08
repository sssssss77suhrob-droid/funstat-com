"""
Collector — Telethon orqali Telegram'dan ma'lumot yig'adi.
Bu modul foydalanuvchi va guruh ma'lumotlarini bazaga saqlaydi.
"""

from telethon import TelegramClient, events
from telethon.tl.types import (
    User, Channel, Chat,
    MessageEntityMention, PeerUser, PeerChannel
)
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import (
    TelegramUser, TelegramGroup, GroupMembership,
    UserMessage, NameHistory, async_session
)
from datetime import datetime
from loguru import logger
import asyncio
import os


API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

client = TelegramClient("funstat_session", API_ID, API_HASH)


async def get_or_create_user(session: AsyncSession, tg_user: User) -> TelegramUser:
    """Foydalanuvchini bazadan olish yoki yangi yaratish"""
    result = await session.execute(
        select(TelegramUser).where(TelegramUser.id == tg_user.id)
    )
    db_user = result.scalar_one_or_none()

    if db_user is None:
        db_user = TelegramUser(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            is_bot=tg_user.bot,
            is_premium=getattr(tg_user, "premium", False),
        )
        session.add(db_user)
        logger.info(f"Yangi foydalanuvchi saqlandi: {tg_user.id}")
    else:
        # O'zgarishlarni tekshirish va tarixi saqlash
        changed = False
        if db_user.username != tg_user.username or db_user.first_name != tg_user.first_name:
            history = NameHistory(
                user_id=db_user.id,
                username=db_user.username,
                first_name=db_user.first_name,
                last_name=db_user.last_name,
            )
            session.add(history)
            changed = True

        if changed:
            db_user.username = tg_user.username
            db_user.first_name = tg_user.first_name
            db_user.last_name = tg_user.last_name

        db_user.last_seen = datetime.utcnow()

    await session.commit()
    return db_user


async def get_or_create_group(session: AsyncSession, group_id: int, title: str,
                               username: str = None, is_channel: bool = False) -> TelegramGroup:
    """Guruhni bazadan olish yoki yangi yaratish"""
    result = await session.execute(
        select(TelegramGroup).where(TelegramGroup.id == group_id)
    )
    db_group = result.scalar_one_or_none()

    if db_group is None:
        db_group = TelegramGroup(
            id=group_id,
            title=title,
            username=username,
            is_channel=is_channel,
        )
        session.add(db_group)
        await session.commit()

    return db_group


async def fetch_user_full_info(user_id: int) -> dict:
    """Foydalanuvchi haqida to'liq ma'lumot olish"""
    try:
        full = await client(GetFullUserRequest(user_id))
        user = full.users[0]
        full_user = full.full_user

        return {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "bio": full_user.about,
            "is_premium": getattr(user, "premium", False),
            "is_bot": user.bot,
            "phone": getattr(user, "phone", None),
        }
    except UserPrivacyRestrictedError:
        logger.warning(f"Foydalanuvchi {user_id} maxfiylik sozlamasi yopiq")
        return None
    except FloodWaitError as e:
        logger.warning(f"FloodWait: {e.seconds} soniya kutish kerak")
        await asyncio.sleep(e.seconds)
        return None
    except Exception as e:
        logger.error(f"Xatolik: {e}")
        return None


async def fetch_group_members(group_username: str) -> list:
    """Guruh a'zolarini olish"""
    try:
        entity = await client.get_entity(group_username)
        members = []
        async for member in client.iter_participants(entity, aggressive=False):
            if isinstance(member, User) and not member.bot:
                members.append({
                    "id": member.id,
                    "username": member.username,
                    "first_name": member.first_name,
                    "last_name": member.last_name,
                })
        logger.info(f"{group_username} dan {len(members)} a'zo olindi")
        return members
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
        return []
    except Exception as e:
        logger.error(f"Guruh a'zolari olishda xato: {e}")
        return []


async def fetch_user_messages(group_username: str, user_id: int, limit: int = 50) -> list:
    """Foydalanuvchining guruhda yozgan xabarlarini olish"""
    try:
        entity = await client.get_entity(group_username)
        messages = []
        async for msg in client.iter_messages(entity, from_user=user_id, limit=limit):
            if msg.text:
                messages.append({
                    "id": msg.id,
                    "text": msg.text,
                    "date": msg.date,
                    "views": getattr(msg, "views", 0) or 0,
                    "forwards": getattr(msg, "forwards", 0) or 0,
                })
        return messages
    except Exception as e:
        logger.error(f"Xabarlar olishda xato: {e}")
        return []


async def scan_group(group_username: str):
    """Guruhni to'liq skanerlash va bazaga saqlash"""
    async with async_session() as session:
        try:
            entity = await client.get_entity(group_username)
            is_channel = isinstance(entity, Channel) and entity.broadcast

            db_group = await get_or_create_group(
                session,
                group_id=entity.id,
                title=entity.title,
                username=getattr(entity, "username", None),
                is_channel=is_channel
            )

            # A'zolarni yig'ish (guruhlar uchun)
            if not is_channel:
                members = await fetch_group_members(group_username)
                for m in members:
                    tg_user_obj = await client.get_entity(m["id"])
                    db_user = await get_or_create_user(session, tg_user_obj)

                    # Guruh a'zoligini saqlash
                    existing = await session.execute(
                        select(GroupMembership).where(
                            GroupMembership.user_id == db_user.id,
                            GroupMembership.group_id == db_group.id
                        )
                    )
                    if not existing.scalar_one_or_none():
                        membership = GroupMembership(
                            user_id=db_user.id,
                            group_id=db_group.id,
                            is_active=True
                        )
                        session.add(membership)

                await session.commit()
                logger.info(f"{group_username} skanerlash tugadi")

        except Exception as e:
            logger.error(f"Guruh skanerlashda xato: {e}")


async def search_user_by_username(username: str) -> dict | None:
    """Username bo'yicha foydalanuvchi qidirish"""
    try:
        username = username.lstrip("@")
        entity = await client.get_entity(username)
        if isinstance(entity, User):
            return await fetch_user_full_info(entity.id)
        return None
    except Exception as e:
        logger.error(f"Foydalanuvchi qidirishda xato: {e}")
        return None


async def start_collector():
    """Kollektorni ishga tushirish"""
    await client.start()
    logger.info("Collector ishga tushdi ✅")
