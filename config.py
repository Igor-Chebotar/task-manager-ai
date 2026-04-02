"""Конфигурация бота - загрузка из .env через pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    telegram_bot_token: str

    # БД
    database_url: str

    # Gemini
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    # Google Calendar OAuth2
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/callback"

    # YouGile
    yougile_api_key: str = ""
    yougile_base_url: str = "https://ru.yougile.com/api-v2"

    # если не задан - токены хранятся без шифрования
    encryption_key: str = ""

    log_level: str = "INFO"
    timezone: str = "Europe/Moscow"
    max_context_messages: int = 10
    rate_limit_rpm: int = 15
    health_check_port: int = 8080


settings = Settings()
