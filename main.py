"""Точка входа - polling + HTTP-сервер для OAuth callback."""

import asyncio
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, text

from config import settings
from database.models import User
from database.session import async_session_factory, engine, init_db, close_db
from handlers import commands_router, messages_router, callbacks_router
from handlers.commands import oauth_state_map
from middlewares import RateLimitMiddleware, DbSessionMiddleware, AuthMiddleware
from services.calendar_integration import CalendarService

START_TIME = time.time()

_bot: Bot | None = None


def setup_logging() -> None:
    """Логирование: stdout + ротация в logs/bot.log."""
    os.makedirs("logs", exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    stdout_fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    stdout_handler.setFormatter(stdout_fmt)

    file_handler = RotatingFileHandler(
        "logs/bot.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_fmt)

    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(file_handler)

    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


async def health_handler(request: web.Request) -> web.Response:
    """GET /health."""
    uptime = int(time.time() - START_TIME)
    active_users = 0
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(DISTINCT user_id) FROM dialog_messages "
                    "WHERE created_at > NOW() - INTERVAL '24 hours'"
                )
            )
            active_users = result.scalar() or 0
    except Exception:
        pass

    return web.json_response({
        "status": "ok",
        "uptime_seconds": uptime,
        "active_users_24h": active_users,
    })


async def oauth_callback_handler(request: web.Request) -> web.Response:
    """GET /callback - OAuth2 redirect от Google."""
    logger = logging.getLogger(__name__)

    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")

    if error:
        logger.warning("OAuth ошибка: %s", error)
        return web.Response(
            text="<html><body><h2>Авторизация отменена</h2>"
                 "<p>Вы можете закрыть эту страницу и вернуться в Telegram.</p>"
                 "</body></html>",
            content_type="text/html",
        )

    if not code or not state:
        return web.Response(
            text="<html><body><h2>Ошибка</h2>"
                 "<p>Отсутствуют параметры code или state.</p>"
                 "</body></html>",
            content_type="text/html",
            status=400,
        )

    telegram_id = oauth_state_map.pop(state, None)
    if not telegram_id:
        logger.warning("Неизвестный OAuth state: %s", state[:16])
        return web.Response(
            text="<html><body><h2>Ошибка</h2>"
                 "<p>Ссылка авторизации устарела. Отправьте /calendar в Telegram заново.</p>"
                 "</body></html>",
            content_type="text/html",
            status=400,
        )

    try:
        async with async_session_factory() as session:
            stmt = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                logger.error("Пользователь telegram_id=%d не найден", telegram_id)
                return web.Response(
                    text="<html><body><h2>Ошибка</h2>"
                         "<p>Пользователь не найден. Отправьте /start в Telegram.</p>"
                         "</body></html>",
                    content_type="text/html",
                    status=404,
                )

            calendar_service = CalendarService()
            success = await calendar_service.exchange_code(code, user, session)

            if success:
                logger.info("OAuth успех для telegram_id=%d", telegram_id)

                if _bot:
                    try:
                        from handlers.callbacks import onboarding_yougile_msg
                        interim_msg_id = onboarding_yougile_msg.pop(telegram_id, None)
                        if interim_msg_id:
                            try:
                                await _bot.delete_message(
                                    chat_id=telegram_id,
                                    message_id=interim_msg_id,
                                )
                            except Exception:
                                pass

                        reply_markup = None
                        if interim_msg_id:
                            reply_markup = InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(
                                    text="⏭ Далее - YouGile",
                                    callback_data="onboard_to_yougile",
                                ),
                            ]])

                        await _bot.send_message(
                            chat_id=telegram_id,
                            text="✅ Google Calendar успешно подключён!\n"
                                 "Теперь ты можешь управлять событиями через текстовые команды.",
                            reply_markup=reply_markup,
                        )
                    except Exception as exc:
                        logger.warning("Не удалось отправить уведомление: %s", exc)

                return web.Response(
                    text="<html><body>"
                         "<h2>✅ Google Calendar подключён!</h2>"
                         "<p>Вернитесь в Telegram - бот готов к работе.</p>"
                         "</body></html>",
                    content_type="text/html",
                )
            else:
                return web.Response(
                    text="<html><body><h2>Ошибка</h2>"
                         "<p>Не удалось подключить Google Calendar. "
                         "Попробуйте /calendar в Telegram заново.</p>"
                         "</body></html>",
                    content_type="text/html",
                    status=500,
                )

    except Exception as exc:
        logger.error("Ошибка OAuth callback: %s", exc)
        return web.Response(
            text="<html><body><h2>Ошибка сервера</h2>"
                 "<p>Попробуйте /calendar в Telegram заново.</p>"
                 "</body></html>",
            content_type="text/html",
            status=500,
        )


async def run_http_server() -> None:
    """Health check + OAuth callback на одном порту."""
    logger = logging.getLogger(__name__)
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/callback", oauth_callback_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.health_check_port)
    await site.start()
    logger.info("HTTP-сервер на порту %d", settings.health_check_port)
    while True:
        await asyncio.sleep(3600)


async def on_startup(bot: Bot) -> None:
    global _bot
    _bot = bot
    logger = logging.getLogger(__name__)
    await init_db()
    bot_info = await bot.me()
    logger.info("Бот запущен: @%s (id=%d)", bot_info.username, bot_info.id)


async def on_shutdown(bot: Bot) -> None:
    global _bot
    _bot = None
    logger = logging.getLogger(__name__)
    logger.info("Остановка бота...")
    await close_db()
    await bot.session.close()


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Инициализация...")

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(DbSessionMiddleware(async_session_factory))
    dp.message.middleware(AuthMiddleware())

    dp.callback_query.middleware(DbSessionMiddleware(async_session_factory))
    dp.callback_query.middleware(AuthMiddleware())

    dp.include_router(commands_router)
    dp.include_router(callbacks_router)
    dp.include_router(messages_router)

    logger.info("Запуск polling + HTTP-сервера...")
    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=["message", "callback_query"]),
            run_http_server(),
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен")
