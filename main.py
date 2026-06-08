"""
Funstat Bot — Asosiy ishga tushirish fayli
"""

import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from loguru import logger

from database.models import init_db
from bot.handlers import router
from bot.admin import admin_router
from collector.telegram_collector import start_collector, client

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


async def on_startup(bot: Bot):
    """Bot ishga tushganda"""
    logger.info("✅ Funstat Bot ishga tushdi!")
    await init_db()
    logger.info("✅ Ma'lumotlar bazasi tayyor!")

    # Kollektorni ishga tushirish
    try:
        await start_collector()
        logger.info("✅ Telegram Collector ishga tushdi!")
    except Exception as e:
        logger.warning(f"⚠️ Collector ishga tushmadi: {e}")

    # Adminlarga xabar
    admin_ids = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, "✅ <b>Funstat Bot ishga tushdi!</b>", parse_mode="HTML")
        except Exception:
            pass


async def on_shutdown(bot: Bot):
    """Bot to'xtaganda"""
    logger.info("Bot to'xtatilmoqda...")
    if client.is_connected():
        await client.disconnect()


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN .env faylida yo'q!")

    # Redis storage (FSM uchun)
    try:
        storage = RedisStorage.from_url(REDIS_URL)
    except Exception:
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        logger.warning("Redis ulashilmadi, MemoryStorage ishlatilmoqda")

    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=storage)

    # Routerlarni ulash
    dp.include_router(admin_router)
    dp.include_router(router)

    # Lifecycle
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("🚀 Bot ishga tushmoqda...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
