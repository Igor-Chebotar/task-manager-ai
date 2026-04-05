"""Middleware авторизации - находит или создаёт юзера по telegram_id."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Ищет юзера в БД, если нет - создаёт. Кладёт в data["user"]."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = None
        if isinstance(event, (Message, CallbackQuery)):
            telegram_user = event.from_user
        else:
            return await handler(event, data)

        if not telegram_user:
            return await handler(event, data)

        session: AsyncSession = data["session"]
        user = await self._get_or_create_user(
            session, telegram_user.id, telegram_user.username,
        )
        data["user"] = user
        return await handler(event, data)

    async def _get_or_create_user(
        self, session: AsyncSession, telegram_id: int, username: str | None,
    ) -> User:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            if user.username != username:
                user.username = username
                await session.commit()
            return user

        new_user = User(telegram_id=telegram_id, username=username)
        session.add(new_user)
        await session.commit()
        logger.info("Новый пользователь: tg=%d, @%s", telegram_id, username)
        return new_user
