"""Тесты LLM-движка - парсинг, валидация интентов."""

import pytest
from unittest.mock import patch, MagicMock


class TestParseResponse:

    def setup_method(self):
        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel"):
                from services.llm_engine import LLMEngine
                self.engine = LLMEngine()

    def test_valid_json(self):
        raw = '{"intent": "create_event", "confidence": 0.95, "params": {"title": "Встреча", "date": "2026-05-15", "time": "10:00"}, "missing_params": [], "clarification_question": null, "response_text": "Создаю встречу"}'
        result = self.engine._parse_response(raw)
        assert result["intent"] == "create_event"
        assert result["confidence"] == 0.95
        assert result["params"]["title"] == "Встреча"

    def test_invalid_json_fallback(self):
        raw = "это не JSON, а просто текст"
        result = self.engine._parse_response(raw)
        assert result["intent"] == "unknown"
        assert result["confidence"] == 0.0

    def test_markdown_wrapper(self):
        raw = '```json\n{"intent": "check_schedule", "confidence": 0.9, "params": {"date": "2026-05-15"}, "missing_params": [], "clarification_question": null, "response_text": "Проверяю"}\n```'
        result = self.engine._parse_response(raw)
        assert result["intent"] == "check_schedule"
        assert result["params"]["date"] == "2026-05-15"


class TestValidateParsed:

    def setup_method(self):
        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel"):
                from services.llm_engine import LLMEngine
                self.engine = LLMEngine()

    def test_rejects_unknown_intent(self):
        parsed = {
            "intent": "execute_malicious_code",
            "confidence": 1.0,
            "params": {},
            "missing_params": [],
            "response_text": "Выполняю код",
        }
        result = self.engine._validate_parsed(parsed)
        assert result["intent"] == "unknown"

    def test_detects_missing_params(self):
        parsed = {
            "intent": "create_event",
            "confidence": 0.9,
            "params": {"title": "Встреча"},
            "missing_params": [],
            "response_text": "Создаю",
        }
        result = self.engine._validate_parsed(parsed)
        assert "date" in result["missing_params"]
        assert "time" in result["missing_params"]

    def test_fills_defaults(self):
        parsed = {"intent": "unknown"}
        result = self.engine._validate_parsed(parsed)
        assert "confidence" in result
        assert "params" in result
        assert "missing_params" in result

    def test_passes_valid_intent(self):
        parsed = {
            "intent": "create_task",
            "confidence": 0.9,
            "params": {"title": "Задача"},
            "missing_params": [],
            "response_text": "Создаю задачу",
        }
        result = self.engine._validate_parsed(parsed)
        assert result["intent"] == "create_task"
