"""Тесты расписания, свободных слотов и конфликтов."""

import pytest
from unittest.mock import AsyncMock, patch


class TestFormatSchedule:

    @pytest.mark.asyncio
    async def test_format_empty_schedule(self, test_user, mock_session):
        from handlers.messages import _format_schedule
        with patch("handlers.messages._generate_day_summary", new_callable=AsyncMock, return_value=""):
            result = await _format_schedule([], "2026-05-15", test_user, mock_session)
        assert "свободен" in result.lower()

    @pytest.mark.asyncio
    async def test_format_with_events(self, test_user, mock_session):
        from handlers.messages import _format_schedule
        events = [
            {
                "summary": "Созвон",
                "start": {"dateTime": "2026-05-15T10:00:00+03:00"},
                "end": {"dateTime": "2026-05-15T11:00:00+03:00"},
            },
            {
                "summary": "Обед",
                "start": {"dateTime": "2026-05-15T13:00:00+03:00"},
                "end": {"dateTime": "2026-05-15T14:00:00+03:00"},
            },
        ]
        with patch("handlers.messages._generate_day_summary", new_callable=AsyncMock, return_value=""):
            result = await _format_schedule(events, "2026-05-15", test_user, mock_session)
        assert "Созвон" in result
        assert "Обед" in result
        assert "10:00" in result


class TestFreeSlots:

    def test_empty_day(self):
        from handlers.messages import _find_free_slots
        result = _find_free_slots([])
        assert result == ["09:00-18:00"]

    def test_gap_between_events(self):
        from handlers.messages import _find_free_slots
        busy = [(600, 660), (720, 780)]  # 10:00-11:00, 12:00-13:00
        result = _find_free_slots(busy)
        assert "09:00-10:00" in result
        assert "11:00-12:00" in result
        assert "13:00-18:00" in result

    def test_full_day(self):
        from handlers.messages import _find_free_slots
        busy = [(540, 1080)]  # 09:00-18:00
        result = _find_free_slots(busy)
        assert result == []


class TestConflictDetection:

    def test_overlap(self):
        new_start, new_end = 600, 660
        exist_start, exist_end = 630, 690
        assert new_start < exist_end and new_end > exist_start

    def test_no_overlap(self):
        new_start, new_end = 600, 660
        exist_start, exist_end = 720, 780
        assert not (new_start < exist_end and new_end > exist_start)

    def test_adjacent_no_overlap(self):
        new_start, new_end = 600, 660
        exist_start, exist_end = 660, 720
        assert not (new_start < exist_end and new_end > exist_start)
