from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, BigInteger, DateTime, Text, ForeignKey, Integer, Boolean
from datetime import datetime
from typing import Optional, List
import os


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/funstat")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class TelegramUser(Base):
    """Telegram foydalanuvchisi"""
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Bog'liq ma'lumotlar
    name_history: Mapped[List["NameHistory"]] = relationship(back_populates="user", cascade="all, delete")
    messages: Mapped[List["UserMessage"]] = relationship(back_populates="user", cascade="all, delete")
    group_memberships: Mapped[List["GroupMembership"]] = relationship(back_populates="user", cascade="all, delete")


class NameHistory(Base):
    """Foydalanuvchi ism/username o'zgarishlari tarixi"""
    __tablename__ = "name_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("telegram_users.id"), index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["TelegramUser"] = relationship(back_populates="name_history")


class TelegramGroup(Base):
    """Telegram guruhi yoki kanali"""
    __tablename__ = "telegram_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    members_count: Mapped[int] = mapped_column(Integer, default=0)
    is_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_scanned: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    members: Mapped[List["GroupMembership"]] = relationship(back_populates="group", cascade="all, delete")
    messages: Mapped[List["UserMessage"]] = relationship(back_populates="group", cascade="all, delete")


class GroupMembership(Base):
    """Foydalanuvchi qaysi guruhlarda"""
    __tablename__ = "group_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("telegram_users.id"), index=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("telegram_groups.id"), index=True)
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["TelegramUser"] = relationship(back_populates="group_memberships")
    group: Mapped["TelegramGroup"] = relationship(back_populates="members")


class UserMessage(Base):
    """Ommaviy guruhlarda yozilgan xabarlar"""
    __tablename__ = "user_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("telegram_users.id"), index=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("telegram_groups.id"), index=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    reply_to_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    forwards: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["TelegramUser"] = relationship(back_populates="messages")
    group: Mapped["TelegramGroup"] = relationship(back_populates="messages")


class BotUser(Base):
    """Botdan foydalanuvchilar"""
    __tablename__ = "bot_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    credits: Mapped[int] = mapped_column(Integer, default=5)  # Bepul so'rovlar
    total_searches: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TrackedUser(Base):
    """Kuzatilayotgan foydalanuvchilar"""
    __tablename__ = "tracked_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracker_bot_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("bot_users.id"), index=True)
    tracked_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


async def init_db():
    """Bazani yaratish"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
