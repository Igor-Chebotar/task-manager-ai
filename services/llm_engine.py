"""LLM-движок - классификация интентов, извлечение сущностей, контекст диалога."""

import json
import logging
import re
from datetime import datetime
from typing import Any

import pytz
import google.generativeai as genai
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import DialogMessage, User
from services.prompts import (
    ALLOWED_INTENTS, REQUIRED_PARAMS, WEEKDAYS_RU,
    SYSTEM_PROMPT, SUMMARIZE_PROMPT,
)

logger = logging.getLogger(__name__)


class LLMEngine:
    """Движок NLP - интенты, сущности, контекст."""

    def __init__(self) -> None:
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                top_p=0.95,
                max_output_tokens=1024,
            ),
        )
        logger.info("LLM-движок: модель %s", settings.gemini_model)

    async def process_message(
        self, user_message: str, user_id: int, session: AsyncSession,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Обрабатывает сообщение - возвращает dict или list[dict] при мультипланировании."""
        logger.info("Обработка сообщения от user_id=%d", user_id)
        user = await self._get_user(user_id, session)
        history = await self._load_context(user_id, session)

        prompt = self._build_prompt(user_message, history, user)
        raw_response = await self._call_gemini(prompt)
        parsed = self._parse_response(raw_response)

        await self._save_message(user_id, "user", user_message, session)

        if isinstance(parsed, list):
            texts = [item.get("response_text", "") for item in parsed]
            assistant_text = "; ".join(t for t in texts if t) or raw_response
        else:
            assistant_text = parsed.get("response_text", raw_response)

        await self._save_message(user_id, "assistant", assistant_text, session)
        await self._trim_context(user_id, session, user)
        return parsed

    async def _get_user(self, user_id: int, session: AsyncSession) -> User:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one()

    def _build_prompt(
        self, user_message: str, history: list[DialogMessage], user: User,
    ) -> str:
        """Собирает промпт с контекстом, датой и защитой от инъекций."""
        user_tz_name = user.timezone or settings.timezone
        tz = pytz.timezone(user_tz_name)
        now = datetime.now(tz)

        system = SYSTEM_PROMPT.format(
            current_datetime=now.strftime("%Y-%m-%d %H:%M"),
            current_date=now.strftime("%Y-%m-%d"),
            current_weekday=WEEKDAYS_RU[now.weekday()],
            user_timezone=user_tz_name,
        )

        parts = [system]

        if user.context_summary:
            parts.append("--- Краткое резюме предыдущих диалогов ---")
            parts.append(user.context_summary)
            parts.append("--- Конец резюме ---")

        context_lines = []
        for msg in history:
            role_label = "Пользователь" if msg.role == "user" else "Ассистент"
            context_lines.append(f"{role_label}: {msg.content}")

        if context_lines:
            parts.append("--- История диалога ---")
            parts.append("\n".join(context_lines))
            parts.append("--- Конец истории ---")

        parts.append(f"\n<user_message>{user_message}</user_message>")
        parts.append("\nОтветь ТОЛЬКО валидным JSON:")

        return "\n".join(parts)

    async def _call_gemini(self, prompt: str) -> str:
        try:
            response = await self.model.generate_content_async(prompt)
            result = response.text.strip()
            logger.debug("Ответ Gemini: %s", result[:200])
            return result
        except Exception as exc:
            logger.error("Ошибка Gemini API: %s", exc)
            raise RuntimeError(f"Ошибка LLM: {exc}") from exc

    def _parse_response(self, raw_response: str) -> dict[str, Any] | list[dict[str, Any]]:
        """Парсит JSON из ответа Gemini, чистит markdown-обёртки."""
        cleaned = raw_response.strip()

        code_block = re.search(r'```(?:json|JSON)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
        if code_block:
            cleaned = code_block.group(1).strip()

        cleaned = cleaned.replace('```json', '').replace('```JSON', '').replace('```', '').strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            json_match = re.search(r'(\{.*\}|\[.*\])', cleaned, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    logger.warning("Не удалось распарсить JSON: %s", raw_response[:300])
                    return {
                        "intent": "unknown", "confidence": 0.0, "params": {},
                        "missing_params": [], "response_text": cleaned,
                    }
            else:
                logger.warning("JSON не найден в ответе: %s", raw_response[:300])
                return {
                    "intent": "unknown", "confidence": 0.0, "params": {},
                    "missing_params": [], "response_text": cleaned,
                }

        if isinstance(parsed, list):
            return [self._validate_parsed(item) for item in parsed]
        return self._validate_parsed(parsed)

    def _validate_parsed(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Проставляет дефолты и проверяет интент по белому списку."""
        defaults = {
            "intent": "unknown", "confidence": 0.0, "params": {},
            "missing_params": [], "clarification_question": None,
            "response_text": "Не удалось обработать запрос.",
        }
        for key, val in defaults.items():
            if key not in parsed:
                parsed[key] = val

        intent = parsed["intent"]
        if intent not in ALLOWED_INTENTS:
            logger.warning("Интент '%s' не в белом списке", intent)
            parsed["intent"] = "unknown"
            parsed["response_text"] = (
                "Я могу помочь только с управлением задачами "
                "и расписанием. Попробуй сформулировать запрос иначе."
            )
            return parsed

        if intent in REQUIRED_PARAMS:
            params = parsed.get("params", {})
            missing = [p for p in REQUIRED_PARAMS[intent] if not params.get(p)]
            if missing:
                parsed["missing_params"] = missing

        return parsed

    async def _load_context(self, user_id: int, session: AsyncSession) -> list[DialogMessage]:
        """Последние N сообщений диалога."""
        stmt = (
            select(DialogMessage).where(DialogMessage.user_id == user_id)
            .order_by(DialogMessage.created_at.desc())
            .limit(settings.max_context_messages)
        )
        result = await session.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def _save_message(self, user_id: int, role: str, content: str, session: AsyncSession) -> None:
        message = DialogMessage(user_id=user_id, role=role, content=content)
        session.add(message)
        await session.commit()

    async def _trim_context(self, user_id: int, session: AsyncSession, user: User) -> None:
        """Удаляет старые сообщения, предварительно суммаризируя."""
        count_stmt = (
            select(DialogMessage.id).where(DialogMessage.user_id == user_id)
            .order_by(DialogMessage.created_at.desc())
        )
        result = await session.execute(count_stmt)
        all_ids = [row[0] for row in result.all()]

        if len(all_ids) <= settings.max_context_messages:
            return

        ids_to_delete = all_ids[settings.max_context_messages:]

        old_msgs_stmt = (
            select(DialogMessage).where(DialogMessage.id.in_(ids_to_delete))
            .order_by(DialogMessage.created_at.asc())
        )
        old_result = await session.execute(old_msgs_stmt)
        old_messages = old_result.scalars().all()

        await self._summarize_context(old_messages, user, session)

        delete_stmt = delete(DialogMessage).where(DialogMessage.id.in_(ids_to_delete))
        await session.execute(delete_stmt)
        await session.commit()
        logger.debug("Удалено %d старых сообщений, user_id=%d", len(ids_to_delete), user_id)

    async def _summarize_context(self, messages: list, user: User, session: AsyncSession) -> None:
        """Сжимает старые сообщения через Gemini и сохраняет в user.context_summary."""
        if not messages:
            return

        dialog_lines = []
        for msg in messages:
            role_label = "Пользователь" if msg.role == "user" else "Ассистент"
            dialog_lines.append(f"{role_label}: {msg.content}")

        dialog_text = "\n".join(dialog_lines)
        if user.context_summary:
            dialog_text = f"Предыдущее резюме: {user.context_summary}\n\nНовый диалог:\n{dialog_text}"

        prompt = SUMMARIZE_PROMPT.format(dialog_text=dialog_text)
        try:
            response = await self.model.generate_content_async(prompt)
            user.context_summary = response.text.strip()
            await session.commit()
            logger.info("Контекст суммаризирован для user_id=%d", user.id)
        except Exception as exc:
            logger.warning("Не удалось суммаризировать: %s", exc)
