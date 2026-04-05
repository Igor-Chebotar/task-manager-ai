"""Middleware для инъекции сессии БД в каждый запрос."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Создаёт сессию SQLAlchemy на каждый запрос и кладёт в data["session"]."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            try:
                return await handler(event, data)
            except Exception as exc:
                await session.rollback()
                logger.error("Ошибка в handler, rollback: %s", exc)
                raise
