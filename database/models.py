"""ORM-модели - пользователи и история диалогов."""

import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """Профиль пользователя с привязками к внешним сервисам."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255))

    timezone: Mapped[str | None] = mapped_column(String(50))

    # OAuth2-токены Google Calendar
    google_access_token: Mapped[str | None] = mapped_column(Text)
    google_refresh_token: Mapped[str | None] = mapped_column(Text)
    google_token_expiry: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    yougile_api_key: Mapped[str | None] = mapped_column(Text)

    context_summary: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    messages: Mapped[list["DialogMessage"]] = relationship(
        "DialogMessage", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, tg={self.telegram_id})>"


class DialogMessage(Base):
    """Одно сообщение в диалоге (для контекста LLM)."""

    __tablename__ = "dialog_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="messages")

    def __repr__(self) -> str:
        return f"<DialogMessage(id={self.id}, role='{self.role}')>"
