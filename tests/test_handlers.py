"""Тесты команд и rate limiter."""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestCommands:

    @pytest.mark.asyncio
    async def test_start_command(self, mock_message, test_user, mock_session):
        from handlers.commands import cmd_start
        await cmd_start(mock_message, test_user, mock_session)
        mock_message.answer.assert_called_once()
        call_text = mock_message.answer.call_args[0][0]
        assert "Привет" in call_text

    @pytest.mark.asyncio
    async def test_help_command(self, mock_message, test_user, mock_session):
        from handlers.commands import cmd_help
        await cmd_help(mock_message, test_user, mock_session)
        mock_message.answer.assert_called_once()
        call_text = mock_message.answer.call_args[0][0]
        assert "умею" in call_text


class TestRateLimiter:

    @pytest.mark.asyncio
    async def test_allows_normal_traffic(self):
        from middlewares.rate_limit import RateLimitMiddleware

        limiter = RateLimitMiddleware()
        handler = AsyncMock()
        message = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 999
        message.answer = AsyncMock()

        await limiter(handler, message, {})
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocks_excess(self):
        from middlewares.rate_limit import RateLimitMiddleware

        limiter = RateLimitMiddleware()
        limiter.limit = 3
        handler = AsyncMock()
        message = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 888
        message.answer = AsyncMock()

        for _ in range(3):
            await limiter(handler, message, {})
        assert handler.call_count == 3

        await limiter(handler, message, {})
        assert handler.call_count == 3
        message.answer.assert_called()
