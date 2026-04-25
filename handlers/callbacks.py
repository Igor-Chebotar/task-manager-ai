"""Обработчики inline-кнопок (callback queries)."""

import logging
import secrets
from typing import Any

import pytz
from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from handlers.commands import (
    TIMEZONE_OPTIONS,
    _kb_connect_calendar,
    _kb_connect_yougile,
    _kb_timezone,
    generate_and_send_oauth,
)

logger = logging.getLogger(__name__)

router = Router(name="callbacks")

waiting_custom_tz: set[int] = set()

onboarding_tz_flow: set[int] = set()

waiting_yougile_key: set[int] = set()

onboarding_yougile_msg: dict[int, int] = {}


callback_data_store: dict[str, dict[str, Any]] = {}


def store_callback(data: dict[str, Any]) -> str:
    """Сохраняет данные и возвращает короткий 8-символьный ID."""
    key = secrets.token_hex(4)
    callback_data_store[key] = data
    return key


def get_callback(key: str) -> dict[str, Any] | None:
    """Достаёт данные по короткому ID (без удаления, чтобы кнопку можно было нажать повторно)."""
    return callback_data_store.get(key)


@router.callback_query(lambda c: c.data == "onboard_start")
async def cb_onboard_start(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    onboarding_tz_flow.add(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "🕐 Укажи свой часовой пояс:", reply_markup=_kb_timezone(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("tz_set:"))
async def cb_timezone_set(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    tz_value = callback.data.split(":", 1)[1]
    user.timezone = tz_value
    await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Часовой пояс: {tz_value}")

    if callback.from_user.id in onboarding_tz_flow:
        onboarding_tz_flow.discard(callback.from_user.id)
        await callback.message.answer(
            "📅 Подключим Google Calendar?",
            reply_markup=_kb_connect_calendar(),
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "tz_custom")
async def cb_timezone_custom(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    waiting_custom_tz.add(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Напиши часовой пояс текстом, например: <b>Europe/London</b>\n"
        "Полный список: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "onboard_calendar_connect")
async def cb_onboard_calendar_connect(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await generate_and_send_oauth(callback, user, session)
    interim_msg = await callback.message.answer(
        "После авторизации в Google нажми кнопку ниже:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="⏭ Далее — YouGile",
                callback_data="onboard_to_yougile",
            ),
        ]]),
    )
    onboarding_yougile_msg[callback.from_user.id] = interim_msg.message_id
    await callback.answer()


@router.callback_query(lambda c: c.data == "onboard_calendar_skip")
async def cb_onboard_calendar_skip(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "📋 Подключаем YouGile", reply_markup=_kb_connect_yougile(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "onboard_to_yougile")
async def cb_onboard_to_yougile(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "📋 Подключаем YouGile", reply_markup=_kb_connect_yougile(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "onboard_yougile_connect")
async def cb_onboard_yougile_connect(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    waiting_yougile_key.add(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Отправь мне API-ключ YouGile.\n\n"
        "Ключ можно получить через YouGile API "
        "(POST-запрос на /auth/keys с логином и паролем).\n"
        "Подробнее: ru.yougile.com/api-v2#section/Avtorizaciya"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "onboard_yougile_skip")
async def cb_onboard_yougile_skip(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "🎉 Настройка завершена! Теперь просто пиши мне задачи "
        "на обычном языке."
    )
    await callback.answer()


@router.callback_query(lambda c: c.data in ("calendar_connect", "calendar_reconnect"))
async def cb_calendar_connect(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await generate_and_send_oauth(callback, user, session)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("confirm_delete:"))
async def cb_confirm_delete(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions, format_date
    from services.calendar_integration import CalendarService

    telegram_id = callback.from_user.id
    action = pending_actions.pop(telegram_id, None)
    if not action:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    params = action["params"]
    calendar_service = CalendarService()
    result = await calendar_service.delete_event(
        user=user, session=session,
        title=params.get("title", ""),
        date=params.get("date", ""),
    )

    if result:
        date_str = format_date(params.get("date", ""))
        title = params.get("title", "без названия")
        await callback.message.edit_text(
            f"🗑 Сделано! Событие «{title}» ({date_str}) удалено из календаря."
        )
        from services.llm_engine import LLMEngine
        _llm = LLMEngine()
        await _llm._save_message(
            user.id, "assistant",
            f"[Система] Удалено событие «{title}» на {params.get('date', '')}",
            session,
        )
    else:
        await callback.message.edit_text(
            "Не удалось удалить событие. Проверь подключение: /calendar"
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("confirm_move:"))
async def cb_confirm_move(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions, format_date
    from services.calendar_integration import CalendarService

    telegram_id = callback.from_user.id
    action = pending_actions.pop(telegram_id, None)
    if not action:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    params = action["params"]
    calendar_service = CalendarService()
    new_date = params.get("new_date", params.get("date", ""))
    new_time = params.get("new_time", params.get("time", ""))

    result = await calendar_service.move_event(
        user=user, session=session,
        title=params.get("title", ""),
        old_date=params.get("date", ""),
        new_date=new_date,
        new_time=new_time,
    )

    if result:
        title = params.get("title", "без названия")
        date_str = format_date(new_date)
        await callback.message.edit_text(
            f"📦 Готово! «{title}» перенесено на {date_str} в {new_time}."
        )
        from services.llm_engine import LLMEngine
        _llm = LLMEngine()
        await _llm._save_message(
            user.id, "assistant",
            f"[Система] Перенесено «{title}» на {new_date} {new_time}",
            session,
        )
    else:
        await callback.message.edit_text(
            "Не удалось перенести событие. Проверь подключение: /calendar"
        )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("confirm_conflict:"))
async def cb_confirm_conflict(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions, format_date, _kb_after_create_event
    from services.calendar_integration import CalendarService

    telegram_id = callback.from_user.id
    action = pending_actions.pop(telegram_id, None)
    if not action:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    params = action["params"]
    calendar_service = CalendarService()
    result = await calendar_service.create_event(
        user=user, session=session,
        title=params.get("title", "Без названия"),
        date=params.get("date", ""),
        time=params.get("time", ""),
        end_time=params.get("end_time"),
        description=params.get("description", ""),
    )

    if result:
        title = params.get("title", "без названия")
        date_str = format_date(params.get("date", ""))
        time_str = params.get("time", "")
        end_time_str = params.get("end_time", "")
        time_range = f"{time_str} – {end_time_str}" if end_time_str else time_str
        await callback.message.edit_text(
            f"✅ Создано: «{title}»\n"
            f"📅 {date_str} · {time_range}",
            reply_markup=_kb_after_create_event(params),
        )
    else:
        await callback.message.edit_text(
            "Не удалось создать событие. Проверь подключение: /calendar"
        )
    await callback.answer()


@router.callback_query(lambda c: c.data == "cancel_action")
async def cb_cancel_action(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions

    telegram_id = callback.from_user.id
    pending_actions.pop(telegram_id, None)
    await callback.message.edit_text("❌ Действие отменено.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("add_event:"))
async def cb_add_event_for_date(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import format_date, pending_actions

    date = callback.data.split(":", 1)[1]
    date_str = format_date(date)

    pending_actions[callback.from_user.id] = {
        "intent": "prefill_date",
        "params": {"date": date},
    }

    await callback.message.answer(
        f"Какое дело добавить на {date_str}? Напиши название и время."
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("del_event:"))
async def cb_del_event_for_date(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import format_date
    from services.calendar_integration import CalendarService
    from datetime import datetime

    date = callback.data.split(":", 1)[1]
    date_str = format_date(date)

    calendar_service = CalendarService()
    events = await calendar_service.check_schedule(
        user=user, session=session, date=date,
    )

    if not events:
        await callback.message.answer(
            f"На {date_str} дел нет — удалять нечего 🤷"
        )
        await callback.answer()
        return

    rows = []
    for event in events:
        summary = event.get("summary", "Без названия")
        start_raw = event.get("start", {}).get("dateTime", "")
        time_label = ""
        if start_raw:
            try:
                dt = datetime.fromisoformat(start_raw)
                time_label = f" ({dt.strftime('%H:%M')})"
            except ValueError:
                pass

        key = store_callback({"title": summary, "date": date})
        rows.append([
            InlineKeyboardButton(
                text=f"{summary}{time_label}",
                callback_data=f"pick_del:{key}",
            )
        ])

    rows.append([InlineKeyboardButton(
        text="🗑 Очистить весь день",
        callback_data=f"clear_day:{date}",
    )])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")])

    await callback.message.answer(
        f"Какое дело удалить с {date_str}?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("pick_del:"))
async def cb_pick_delete(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import format_date, pending_actions, _kb_confirm_delete

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    title = data["title"]
    date = data["date"]
    date_str = format_date(date)

    pending_actions[callback.from_user.id] = {
        "intent": "delete_event",
        "params": {"title": title, "date": date},
    }

    await callback.message.edit_text(
        f"Точно удаляем «{title}» на {date_str}?",
        reply_markup=_kb_confirm_delete(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("clear_day:"))
async def cb_clear_day_confirm(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import format_date
    from services.calendar_integration import CalendarService
    from datetime import datetime

    date = callback.data.split(":", 1)[1]
    date_str = format_date(date)

    calendar_service = CalendarService()
    events = await calendar_service.check_schedule(
        user=user, session=session, date=date,
    )

    if not events:
        await callback.message.edit_text(
            f"На {date_str} дел нет — удалять нечего 🤷"
        )
        await callback.answer()
        return

    lines = [f"Удалить ВСЕ дела с {date_str}? (всего: {len(events)})", ""]
    for event in events:
        summary = event.get("summary", "Без названия")
        start_raw = event.get("start", {}).get("dateTime", "")
        if start_raw:
            try:
                dt = datetime.fromisoformat(start_raw)
                lines.append(f"🕐 {dt.strftime('%H:%M')} — {summary}")
            except ValueError:
                lines.append(f"🕐 {summary}")
        else:
            lines.append(f"🕐 Весь день — {summary}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Да, удалить все",
                callback_data=f"confirm_clear:{date}",
            ),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"),
        ]]),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("confirm_clear:"))
async def cb_confirm_clear_day(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import format_date
    from services.calendar_integration import CalendarService

    date = callback.data.split(":", 1)[1]
    date_str = format_date(date)

    calendar_service = CalendarService()
    events = await calendar_service.check_schedule(
        user=user, session=session, date=date,
    )

    if not events:
        await callback.message.edit_text(
            f"На {date_str} дел нет — удалять нечего 🤷"
        )
        await callback.answer()
        return

    deleted_count = 0
    for event in events:
        summary = event.get("summary", "")
        result = await calendar_service.delete_event(
            user=user, session=session, title=summary, date=date,
        )
        if result:
            deleted_count += 1

    await callback.message.edit_text(
        f"🗑 Готово! Все дела с {date_str} удалены (всего: {deleted_count})"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("quick_del:"))
async def cb_quick_delete(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import format_date, pending_actions, _kb_confirm_delete

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    title = data["title"]
    date = data["date"]
    date_str = format_date(date)

    pending_actions[callback.from_user.id] = {
        "intent": "delete_event",
        "params": {"title": title, "date": date},
    }

    await callback.message.answer(
        f"Точно удаляем «{title}» на {date_str}?",
        reply_markup=_kb_confirm_delete(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("quick_move:"))
async def cb_quick_move(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    title = data["title"]

    pending_actions[callback.from_user.id] = {
        "intent": "prefill_move",
        "params": {"title": title, "date": data["date"]},
    }

    await callback.message.answer(
        f"Куда перенести «{title}»? Напиши дату и время."
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("quick_edit:"))
async def cb_quick_edit(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    title = data["title"]

    rename_key = store_callback(data)
    duration_key = store_callback(data)
    move_key = store_callback(data)

    await callback.message.answer(
        f"Что изменить в «{title}»?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Переименовать", callback_data=f"edit_rename:{rename_key}")],
            [InlineKeyboardButton(text="⏱ Изменить длительность", callback_data=f"edit_dur:{duration_key}")],
            [InlineKeyboardButton(text="📦 Перенести", callback_data=f"quick_move:{move_key}")],
        ]),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("edit_rename:"))
async def cb_edit_rename(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    title = data["title"]

    pending_actions[callback.from_user.id] = {
        "intent": "rename_event",
        "params": {"title": title, "date": data["date"]},
    }

    await callback.message.answer(
        f"Напиши новое название для «{title}»"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("edit_dur:"))
async def cb_edit_duration(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    title = data["title"]

    pending_actions[callback.from_user.id] = {
        "intent": "update_duration",
        "params": {"title": title, "date": data["date"]},
    }

    await callback.message.answer(
        f"Напиши новую длительность для «{title}» (например: 30 минут, 1 час)"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("yg_new_task:"))
async def cb_yg_new_task_in_column(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import pending_actions

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    pending_actions[callback.from_user.id] = {
        "intent": "create_task_in_column",
        "params": {"column_id": data["column_id"]},
    }

    await callback.message.answer("Напиши название задачи:")
    await callback.answer()


@router.callback_query(lambda c: c.data == "action_create_task")
async def cb_create_task(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    await callback.message.answer(
        "Напиши, какую задачу создать. Например:\n"
        "Задача: подготовить презентацию до пятницы"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("schedule_day:"))
async def cb_schedule_day(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from handlers.messages import format_date, _kb_after_schedule, _format_schedule
    from services.calendar_integration import CalendarService

    date = callback.data.split(":", 1)[1]

    calendar_service = CalendarService()
    events = await calendar_service.check_schedule(
        user=user, session=session, date=date,
    )
    formatted = await _format_schedule(events, date, user, session)
    await callback.message.answer(formatted, reply_markup=_kb_after_schedule(date))
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("yg_proj:"))
async def cb_yg_project(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from services.yougile_integration import YougileService
    from services.encryption import decrypt_token
    from handlers.messages import pending_actions

    project_id = callback.data.split(":", 1)[1]
    api_key = decrypt_token(user.yougile_api_key)
    yougile = YougileService()
    boards = await yougile.get_boards(api_key, project_id)

    telegram_id = callback.from_user.id
    pending = pending_actions.get(telegram_id)
    has_pending = pending and pending.get("intent") == "create_task_pending"

    if has_pending and len(boards) == 1:
        columns = await yougile.get_columns(api_key, boards[0]["id"])
        task_title = pending["params"].get("title", "")
        rows = []
        for col in columns:
            rows.append([InlineKeyboardButton(
                text=f"📌 {col['title']}",
                callback_data=f"yg_col:{col['id']}",
            )])
        rows.append([InlineKeyboardButton(text="⬅️ Назад к проектам", callback_data="yg_back_proj")])
        await callback.message.edit_text(
            f"📋 Выбери колонку для задачи «{task_title}»:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        await callback.answer()
        return

    rows = []
    for board in boards:
        rows.append([InlineKeyboardButton(
            text=f"📋 {board['title']}",
            callback_data=f"yg_board:{board['id']}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад к проектам", callback_data="yg_back_proj")])

    header = "📁 Доски:"
    if has_pending:
        header = f"📋 Выбери доску для задачи «{pending['params'].get('title', '')}»:"

    await callback.message.edit_text(
        header,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "yg_back_proj")
async def cb_yg_back_projects(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from services.yougile_integration import YougileService
    from services.encryption import decrypt_token

    api_key = decrypt_token(user.yougile_api_key)
    yougile = YougileService()
    projects = await yougile.get_projects(api_key)

    rows = []
    for proj in projects:
        rows.append([InlineKeyboardButton(
            text=f"📁 {proj['title']}",
            callback_data=f"yg_proj:{proj['id']}",
        )])

    await callback.message.edit_text(
        "📋 Проекты YouGile:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("yg_board:"))
async def cb_yg_board(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from services.yougile_integration import YougileService
    from services.encryption import decrypt_token
    from handlers.messages import pending_actions

    board_id = callback.data.split(":", 1)[1]
    api_key = decrypt_token(user.yougile_api_key)
    yougile = YougileService()
    columns = await yougile.get_columns(api_key, board_id)

    telegram_id = callback.from_user.id
    pending = pending_actions.get(telegram_id)
    has_pending = pending and pending.get("intent") == "create_task_pending"

    rows = []
    for col in columns:
        rows.append([InlineKeyboardButton(
            text=f"📌 {col['title']}",
            callback_data=f"yg_col:{col['id']}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="yg_back_proj")])

    header = "📋 Колонки:"
    if has_pending:
        header = f"📋 Выбери колонку для задачи «{pending['params'].get('title', '')}»:"

    await callback.message.edit_text(
        header,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("yg_col:"))
async def cb_yg_column(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    """
    Показывает задачи в колонке.
    Если есть pending create_task_pending — сразу создаёт задачу.
    """
    from services.yougile_integration import YougileService
    from services.encryption import decrypt_token
    from handlers.messages import pending_actions, _kb_after_task

    column_id = callback.data.split(":", 1)[1]
    api_key = decrypt_token(user.yougile_api_key)
    yougile = YougileService()
    telegram_id = callback.from_user.id

    pending = pending_actions.get(telegram_id)
    if pending and pending.get("intent") == "create_task_pending":
        pending_actions.pop(telegram_id, None)
        params = pending["params"]
        title = params.get("title", "Без названия")

        result = await yougile.create_task(
            api_key=api_key,
            title=title,
            column_id=column_id,
            description=params.get("description", ""),
            deadline=params.get("date"),
        )

        if result:
            await callback.message.edit_text(
                f"✅ Задача создана: «{title}»\n"
                f"📋 Колонка выбрана",
                reply_markup=_kb_after_task(column_id),
            )
        else:
            await callback.message.edit_text(
                f"Не удалось создать задачу «{title}». Попробуй ещё раз."
            )
        await callback.answer()
        return

    tasks = await yougile.get_tasks(api_key, column_id)

    rows = []
    if tasks:
        lines = ["📌 Задачи:", ""]
        for i, task in enumerate(tasks, 1):
            title = task.get("title", "Без названия")
            lines.append(f"{i}. {title}")
            key = store_callback({"task_id": task["id"], "title": title})
            rows.append([InlineKeyboardButton(
                text=f"🗑 {i}. {title}"[:40],
                callback_data=f"yg_del_task:{key}",
            )])
        lines.append(f"\nВсего задач: {len(tasks)}")
        text = "\n".join(lines)
    else:
        text = "📌 Задач пока нет"

    if tasks:
        clear_key = store_callback({"column_id": column_id})
        rows.append([InlineKeyboardButton(
            text="🗑 Очистить все задачи",
            callback_data=f"yg_clear_col:{clear_key}",
        )])
    rows.append([InlineKeyboardButton(
        text="➕ Новая задача",
        callback_data=f"yg_new_task:{store_callback({'column_id': column_id})}",
    )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="yg_back_proj")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("yg_clear_col:"))
async def cb_yg_clear_column_confirm(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from services.yougile_integration import YougileService
    from services.encryption import decrypt_token

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    column_id = data["column_id"]
    api_key = decrypt_token(user.yougile_api_key)
    yougile = YougileService()
    tasks = await yougile.get_tasks(api_key, column_id)

    if not tasks:
        await callback.message.edit_text("📌 Задач в колонке нет — удалять нечего.")
        await callback.answer()
        return

    confirm_key = store_callback({"column_id": column_id})
    await callback.message.edit_text(
        f"Удалить ВСЕ задачи из колонки? (всего: {len(tasks)})",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Да, удалить все",
                callback_data=f"yg_confirm_clear:{confirm_key}",
            ),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action"),
        ]]),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("yg_confirm_clear:"))
async def cb_yg_confirm_clear_column(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from services.yougile_integration import YougileService
    from services.encryption import decrypt_token

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    column_id = data["column_id"]
    api_key = decrypt_token(user.yougile_api_key)
    yougile = YougileService()
    deleted = await yougile.clear_column(api_key, column_id)

    await callback.message.edit_text(
        f"🗑 Готово! Все задачи из колонки удалены (всего: {deleted})"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("yg_del_task:"))
async def cb_yg_delete_task(
    callback: CallbackQuery, user: User, session: AsyncSession,
) -> None:
    from services.yougile_integration import YougileService
    from services.encryption import decrypt_token

    key = callback.data.split(":", 1)[1]
    data = get_callback(key)
    if not data:
        await callback.message.edit_text("⏳ Действие устарело, попробуй ещё раз.")
        await callback.answer()
        return

    task_id = data["task_id"]
    title = data.get("title", "задача")

    api_key = decrypt_token(user.yougile_api_key)
    yougile = YougileService()
    result = await yougile.delete_task(api_key, task_id)

    if result:
        await callback.message.edit_text(f"🗑 Задача «{title}» удалена из YouGile")
        from services.llm_engine import LLMEngine
        _llm = LLMEngine()
        await _llm._save_message(
            user.id, "assistant",
            f"[Система] Удалена задача «{title}» из YouGile",
            session,
        )
    else:
        await callback.message.edit_text("Не удалось удалить задачу. Попробуй ещё раз.")
    await callback.answer()
