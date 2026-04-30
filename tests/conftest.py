"""Фикстуры для тестов."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from database.models import User, DialogMessage


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def test_user():
    return User(
        id=1,
        telegram_id=123456789,
        username="testuser",
        google_access_token="test_token",
        google_refresh_token="test_refresh",
        yougile_api_key="test_yougile_key",
        context_summary=None,
    )


@pytest.fixture
def mock_gemini():
    with patch("google.generativeai.configure"):
        with patch("google.generativeai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model_cls.return_value = mock_model
            mock_response = MagicMock()
            mock_response.text = '{"intent": "unknown", "confidence": 1.0, "params": {}, "missing_params": [], "clarification_question": null, "response_text": "test"}'
            mock_model.generate_content_async = AsyncMock(
                return_value=mock_response
            )
            yield mock_model


@pytest.fixture
def mock_message():
    message = AsyncMock()
    message.text = "test message"
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.from_user.first_name = "Test"
    message.from_user.username = "testuser"
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.answer = AsyncMock()
    message.bot = AsyncMock()
    message.bot.edit_message_text = AsyncMock()
    message.bot.delete_message = AsyncMock()
    message.bot.send_chat_action = AsyncMock()
    return message
