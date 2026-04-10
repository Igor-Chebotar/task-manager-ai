"""Интеграция с Google Calendar - OAuth2, CRUD событий."""

import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from google_auth_oauthlib.flow import Flow
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import User
from services.encryption import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class CalendarService:
    """Работа с Google Calendar API."""

    def __init__(self) -> None:
        logger.info("Сервис Google Calendar инициализирован")

    def get_auth_url(self, state: str = "") -> str:
        """Генерирует URL для OAuth2-авторизации."""
        flow = Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uris": [settings.google_redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": GOOGLE_TOKEN_URI,
                }
            },
            scopes=GOOGLE_OAUTH_SCOPES,
        )
        flow.redirect_uri = settings.google_redirect_uri

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        logger.info("URL авторизации Google (state=%s)", state[:8] if state else "none")
        return auth_url

    async def exchange_code(
        self, code: str, user: User, session: AsyncSession,
    ) -> bool:
        """Обменивает authorization code на токены и сохраняет."""
        payload = {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(GOOGLE_TOKEN_URI, data=payload) as resp:
                    if resp.status != 200:
                        logger.error("Ошибка обмена кода: %s", await resp.text())
                        return False
                    token_data = await resp.json()

            user.google_access_token = encrypt_token(token_data["access_token"])
            refresh = token_data.get("refresh_token")
            if refresh:
                user.google_refresh_token = encrypt_token(refresh)
            user.google_token_expiry = datetime.utcnow() + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )
            await session.commit()
            logger.info("Токены Google сохранены для user_id=%d", user.id)
            return True

        except Exception as exc:
            logger.error("Ошибка при обмене authorization code: %s", exc)
            return False

    async def _get_valid_token(self, user: User, session: AsyncSession) -> str | None:
        """Возвращает актуальный access_token, обновляя при необходимости."""
        if not user.google_access_token:
            return None

        access_token = decrypt_token(user.google_access_token)

        if user.google_token_expiry and user.google_token_expiry.replace(tzinfo=None) > (
            datetime.utcnow() + timedelta(minutes=5)
        ):
            return access_token

        if not user.google_refresh_token:
            logger.warning("Нет refresh-токена для user_id=%d", user.id)
            return None

        return await self._refresh_token(user, session)

    async def _refresh_token(self, user: User, session: AsyncSession) -> str | None:
        """Обновляет access_token через refresh_token."""
        refresh_token = decrypt_token(user.google_refresh_token)

        payload = {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(GOOGLE_TOKEN_URI, data=payload) as resp:
                    if resp.status != 200:
                        logger.error("Ошибка обновления токена: %s", await resp.text())
                        return None
                    token_data = await resp.json()

            new_token = token_data["access_token"]
            user.google_access_token = encrypt_token(new_token)
            user.google_token_expiry = datetime.utcnow() + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )
            await session.commit()
            logger.info("Токен Google обновлён для user_id=%d", user.id)
            return new_token

        except Exception as exc:
            logger.error("Ошибка обновления токена: %s", exc)
            return None

    async def _find_event(
        self, token: str, title: str, date: str,
    ) -> dict[str, Any] | None:
        """Ищет событие по названию и дате, возвращает первое найденное."""
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "timeMin": f"{date}T00:00:00Z",
            "timeMax": f"{date}T23:59:59Z",
            "q": title,
            "singleEvents": "true",
        }
        url = f"{GOOGLE_CALENDAR_API}/calendars/primary/events"

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, params=params, headers=headers) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
            events = data.get("items", [])
            return events[0] if events else None
        except Exception as exc:
            logger.error("Ошибка поиска события: %s", exc)
            return None

    async def create_event(
        self, user: User, session: AsyncSession,
        title: str, date: str, time: str,
        end_time: str | None = None, description: str = "",
    ) -> dict[str, Any] | None:
        """Создаёт событие в основном календаре."""
        token = await self._get_valid_token(user, session)
        if not token:
            return None

        start_dt = f"{date}T{time}:00"
        if end_time:
            end_dt = f"{date}T{end_time}:00"
        else:
            start_obj = datetime.strptime(start_dt, "%Y-%m-%dT%H:%M:%S")
            end_obj = start_obj + timedelta(hours=1)
            end_dt = end_obj.strftime("%Y-%m-%dT%H:%M:%S")

        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt, "timeZone": settings.timezone},
            "end": {"dateTime": end_dt, "timeZone": settings.timezone},
        }

        url = f"{GOOGLE_CALENDAR_API}/calendars/primary/events"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(url, json=event_body, headers=headers) as resp:
                    if resp.status == 200:
                        event = await resp.json()
                        logger.info("Создано: '%s' на %s %s", title, date, time)
                        return event
                    else:
                        logger.error("Ошибка создания события: %s", await resp.text())
                        return None
        except Exception as exc:
            logger.error("Ошибка при создании события: %s", exc)
            return None

    async def delete_event(
        self, user: User, session: AsyncSession, title: str, date: str,
    ) -> bool:
        """Удаляет событие по названию и дате."""
        token = await self._get_valid_token(user, session)
        if not token:
            return False

        event = await self._find_event(token, title, date)
        if not event:
            logger.info("Событие '%s' на %s не найдено", title, date)
            return False

        headers = {"Authorization": f"Bearer {token}"}
        delete_url = f"{GOOGLE_CALENDAR_API}/calendars/primary/events/{event['id']}"

        try:
            async with aiohttp.ClientSession() as http:
                async with http.delete(delete_url, headers=headers) as resp:
                    if resp.status == 204:
                        logger.info("Удалено: '%s'", title)
                        return True
                    return False
        except Exception as exc:
            logger.error("Ошибка при удалении события: %s", exc)
            return False

    async def check_schedule(
        self, user: User, session: AsyncSession, date: str,
    ) -> list[dict[str, Any]]:
        """Возвращает список событий на дату."""
        token = await self._get_valid_token(user, session)
        if not token:
            return []

        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "timeMin": f"{date}T00:00:00Z",
            "timeMax": f"{date}T23:59:59Z",
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        url = f"{GOOGLE_CALENDAR_API}/calendars/primary/events"

        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, params=params, headers=headers) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
            events = data.get("items", [])
            logger.info("Найдено %d событий на %s", len(events), date)
            return events
        except Exception as exc:
            logger.error("Ошибка проверки расписания: %s", exc)
            return []

    async def move_event(
        self, user: User, session: AsyncSession,
        title: str, old_date: str, new_date: str, new_time: str,
    ) -> bool:
        """Переносит событие на новую дату/время."""
        token = await self._get_valid_token(user, session)
        if not token:
            return False

        event = await self._find_event(token, title, old_date)
        if not event:
            logger.info("Событие '%s' на %s не найдено для переноса", title, old_date)
            return False

        # вычисляем длительность из оригинального события
        orig_start_raw = event.get("start", {}).get("dateTime", "")
        orig_end_raw = event.get("end", {}).get("dateTime", "")
        try:
            orig_start_dt = datetime.fromisoformat(orig_start_raw)
            orig_end_dt = datetime.fromisoformat(orig_end_raw)
            duration = orig_end_dt - orig_start_dt
        except (ValueError, TypeError):
            duration = timedelta(hours=1)

        new_start = f"{new_date}T{new_time}:00"
        new_start_obj = datetime.strptime(new_start, "%Y-%m-%dT%H:%M:%S")
        new_end_obj = new_start_obj + duration
        new_end = new_end_obj.strftime("%Y-%m-%dT%H:%M:%S")

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        patch_url = f"{GOOGLE_CALENDAR_API}/calendars/primary/events/{event['id']}"
        patch_body = {
            "start": {"dateTime": new_start, "timeZone": settings.timezone},
            "end": {"dateTime": new_end, "timeZone": settings.timezone},
        }

        try:
            async with aiohttp.ClientSession() as http:
                async with http.patch(patch_url, json=patch_body, headers=headers) as resp:
                    if resp.status == 200:
                        logger.info("Перенесено: '%s' на %s %s", title, new_date, new_time)
                        return True
                    logger.warning("PATCH вернул status=%d", resp.status)
                    return False
        except Exception as exc:
            logger.error("Ошибка при переносе события: %s", exc)
            return False

    async def rename_event(
        self, user: User, session: AsyncSession,
        title: str, date: str, new_title: str,
    ) -> bool:
        """Переименовывает событие."""
        token = await self._get_valid_token(user, session)
        if not token:
            return False

        event = await self._find_event(token, title, date)
        if not event:
            logger.info("Событие '%s' на %s не найдено", title, date)
            return False

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        patch_url = f"{GOOGLE_CALENDAR_API}/calendars/primary/events/{event['id']}"

        try:
            async with aiohttp.ClientSession() as http:
                async with http.patch(patch_url, json={"summary": new_title}, headers=headers) as resp:
                    if resp.status == 200:
                        logger.info("Переименовано: '%s' -> '%s'", title, new_title)
                        return True
                    logger.error("Ошибка переименования: %s", await resp.text())
                    return False
        except Exception as exc:
            logger.error("Ошибка при переименовании: %s", exc)
            return False

    async def update_event_duration(
        self, user: User, session: AsyncSession,
        title: str, date: str, new_duration_minutes: int,
    ) -> dict[str, str] | None:
        """Меняет длительность события. Возвращает {start, end} или None."""
        token = await self._get_valid_token(user, session)
        if not token:
            return None

        event = await self._find_event(token, title, date)
        if not event:
            return None

        start_raw = event.get("start", {}).get("dateTime", "")
        if not start_raw:
            return None

        try:
            start_dt = datetime.fromisoformat(start_raw)
        except ValueError:
            return None

        new_end_dt = start_dt + timedelta(minutes=new_duration_minutes)

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        patch_url = f"{GOOGLE_CALENDAR_API}/calendars/primary/events/{event['id']}"
        patch_body = {
            "end": {
                "dateTime": new_end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": settings.timezone,
            },
        }

        try:
            async with aiohttp.ClientSession() as http:
                async with http.patch(patch_url, json=patch_body, headers=headers) as resp:
                    if resp.status == 200:
                        logger.info("Длительность '%s' -> %d мин", title, new_duration_minutes)
                        return {
                            "start": start_dt.strftime("%H:%M"),
                            "end": new_end_dt.strftime("%H:%M"),
                        }
                    logger.error("Ошибка изменения длительности: %s", await resp.text())
                    return None
        except Exception as exc:
            logger.error("Ошибка при изменении длительности: %s", exc)
            return None
