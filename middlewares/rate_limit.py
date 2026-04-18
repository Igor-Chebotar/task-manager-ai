"""Rate limiting - ограничение частоты сообщений от пользователя."""

import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from config import settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    """Блокирует обработку если пользователь шлёт слишком часто."""

    def __init__(self) -> None:
        super().__init__()
        self.limit = settings.rate_limit_rpm
        self.window = 60
        self.user_timestamps: dict[int, list[float]] = defaultdict(list)
        logger.info("Rate limiter: %d req/min", self.limit)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        telegram_user = event.from_user
        if not telegram_user:
            return await handler(event, data)

        telegram_id = telegram_user.id
        now = time.time()

        self.user_timestamps[telegram_id] = [
            ts for ts in self.user_timestamps[telegram_id]
            if now - ts < self.window
        ]

        if len(self.user_timestamps[telegram_id]) >= self.limit:
            logger.warning("Rate limit для tg=%d: %d/%d", telegram_id,
                           len(self.user_timestamps[telegram_id]), self.limit)
            await event.answer("Слишком много запросов, подожди минуту")
            return None

        self.user_timestamps[telegram_id].append(now)
        return await handler(event, data)
