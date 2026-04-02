"""Подключение к БД - движок, сессии, инициализация таблиц."""

import logging

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from database.models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)

# expire_on_commit=False чтобы читать атрибуты после коммита
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Новая сессия - используется в middleware."""
    async with async_session_factory() as session:
        return session


async def init_db() -> None:
    """Создаёт таблицы при запуске (вместо Alembic, для простоты)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Таблицы инициализированы")


async def close_db() -> None:
    """Закрывает пул соединений."""
    await engine.dispose()
    logger.info("Соединение с БД закрыто")
