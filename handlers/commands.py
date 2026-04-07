"""
Обработчики команд Telegram-бота.

Команды: /start, /help, /calendar, /yougile, /timezone
"""

import logging
import secrets

import pytz
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from services.calendar_integration import CalendarService

logger = logging.getLogger(__name__)

router = Router(name="commands")

# Маппинг state -> telegram_id для OAuth callback.
oauth_state_map: dict[str, int] = {}

# Предустановленные часовые пояса
TIMEZONE_OPTIONS = [
    ("Москва (UTC+3)", "Europe/Moscow"),
    ("Минск (UTC+3)", "Europe/Minsk"),
    ("Киев (UTC+2)", "Europe/Kyiv"),
    ("Астана (UTC+6)", "Asia/Almaty"),
]


def _kb_start_setup() -> InlineKeyboardMarkup:
    """Кнопка начала настройки."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="▶️ Начать настройку", callback_data="onboard_start"),
    ]])


def _kb_timezone() -> InlineKeyboardMarkup:
    """Клавиатура выбора часового пояса."""
    rows = []
    for label, _ in TIMEZONE_OPTIONS:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"tz_set:{_}")])
    rows.append([InlineKeyboardButton(text="Другой...", callback_data="tz_custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_connect_calendar() -> InlineKeyboardMarkup:
    """Кнопки подключения Google Calendar в onboarding."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔗 Подключить", callback_data="onboard_calendar_connect"),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="onboard_calendar_skip"),
    ]])


def _kb_connect_yougile() -> InlineKeyboardMarkup:
    """Кнопки подключения YouGile в onboarding."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔗 Подключить", callback_data="onboard_yougile_connect"),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="onboard_yougile_skip"),
    ]])


# ── /start ────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, user: User, session: AsyncSession) -> None:
    """Обработчик команды /start — приветствие и onboarding."""
    first_name = message.from_user.first_name or "друг"
    welcome_text = (
        f"Привет, {first_name}! 🤖 Я ИИ-ассистент для управления твоими делами.\n\n"
        "Понимаю команды на лету, просто напиши:\n"
        "— Создай встречу с Алексом завтра в 15:00\n"
        "— Что запланировано на среду?\n\n"
        "Чтобы я мог управлять расписанием, потребуется пара минут "
        "на настройку: укажем часовой пояс и свяжем бота с Google Calendar "
        "и YouGile.\n\n"
        "Начинаем?"
    )
    await message.answer(welcome_text, reply_markup=_kb_start_setup())
    logger.info("Команда /start от telegram_id=%d", message.from_user.id)


# ── /help ─────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message, user: User, session: AsyncSession) -> None:
    """Обработчик команды /help."""
    help_text = (
        "💡 <b>Что я умею?</b>\n\n"
        "Пиши мне обычным языком, а я сам пойму, куда добавить запись!\n\n"
        "<b>Примеры:</b>\n"
        "— «Создай встречу с Алексом завтра в 15:00» (улетит в Календарь)\n"
        "— «Добавь задачу: подготовить отчёт до пятницы» (улетит в YouGile)\n"
        "— «Удали утреннюю встречу и покажи планы на завтра»\n\n"
        "⚙️ <b>Команды:</b>\n"
        "/start — Главное меню\n"
        "/timezone — Изменить часовой пояс\n"
        "/calendar — Настройки Google Calendar\n"
        "/yougile — Настройки YouGile\n"
        "/help — Эта подсказка"
    )
    await message.answer(help_text, parse_mode="HTML")
    logger.info("Команда /help от telegram_id=%d", message.from_user.id)


# ── /timezone ─────────────────────────────────────────────────

@router.message(Command("timezone"))
async def cmd_timezone(message: Message, user: User, session: AsyncSession) -> None:
    """Обработчик команды /timezone — показ и смена часового пояса."""
    current = user.timezone or "не задан"
    await message.answer(
        f"🕐 Текущий часовой пояс: <b>{current}</b>\n\nВыбери новый:",
        parse_mode="HTML",
        reply_markup=_kb_timezone(),
    )
    logger.info("Команда /timezone от telegram_id=%d", message.from_user.id)


# ── /calendar (бывший /auth) ─────────────────────────────────

@router.message(Command("calendar"))
async def cmd_calendar(message: Message, user: User, session: AsyncSession) -> None:
    """Обработчик команды /calendar — статус и подключение Google Calendar."""
    if user.google_access_token:
        await message.answer(
            "📅 Google Calendar подключён ✅\nХочешь переподключить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔄 Переподключить Google Calendar",
                    callback_data="calendar_reconnect",
                ),
            ]]),
        )
    else:
        await message.answer(
            "📅 Google Calendar не подключён",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔗 Подключить Google Calendar",
                    callback_data="calendar_connect",
                ),
            ]]),
        )
    logger.info("Команда /calendar от telegram_id=%d", message.from_user.id)


# /auth — алиас для /calendar
@router.message(Command("auth"))
async def cmd_auth_alias(message: Message, user: User, session: AsyncSession) -> None:
    """Алиас /auth -> /calendar."""
    await cmd_calendar(message, user, session)


# ── /yougile ──────────────────────────────────────────────────

@router.message(Command("yougile"))
async def cmd_yougile(message: Message, user: User, session: AsyncSession) -> None:
    """Обработчик команды /yougile."""
    from handlers.messages import pending_actions

    if user.yougile_api_key:
        await message.answer(
            "📋 YouGile подключён ✅\n"
            "Чтобы обновить ключ, отправь новый API-ключ."
        )
        pending_actions[message.from_user.id] = {"intent": "awaiting_yougile_key"}
    else:
        await message.answer(
            "📋 Для подключения YouGile отправь мне API-ключ.\n\n"
            "Ключ можно получить через YouGile API "
            "(POST-запрос на /auth/keys с логином и паролем).\n"
            "Подробнее: ru.yougile.com/api-v2#section/Avtorizaciya"
        )
        pending_actions[message.from_user.id] = {"intent": "awaiting_yougile_key"}
    logger.info("Команда /yougile от telegram_id=%d", message.from_user.id)


# ── Вспомогательная функция генерации OAuth-ссылки ────────────

async def generate_and_send_oauth(
    target, user: User, session: AsyncSession,
) -> None:
    """
    Генерирует OAuth-ссылку и отправляет пользователю.

    target может быть Message или CallbackQuery (отправим .message.answer).
    """
    calendar_service = CalendarService()
    try:
        state = secrets.token_urlsafe(32)
        telegram_id = target.from_user.id
        oauth_state_map[state] = telegram_id
        logger.info("Создан OAuth state для telegram_id=%d", telegram_id)

        auth_url = calendar_service.get_auth_url(state=state)

        send_to = target if isinstance(target, Message) else target.message
        await send_to.answer(
            "Для подключения Google Calendar перейди по ссылке:\n\n"
            f"{auth_url}\n\n"
            "После авторизации ты будешь перенаправлен обратно автоматически."
        )
    except Exception as exc:
        logger.error("Ошибка генерации auth URL: %s", exc)
        send_to = target if isinstance(target, Message) else target.message
        await send_to.answer(
            "Не удалось сгенерировать ссылку авторизации.\n"
            "Проверьте настройки Google OAuth в конфигурации."
        )
