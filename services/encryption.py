"""Шифрование токенов и ключей перед сохранением в БД (Fernet)."""

import logging

from cryptography.fernet import Fernet, InvalidToken

from config import settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None

if settings.encryption_key:
    _fernet = Fernet(settings.encryption_key.encode())
    logger.info("Шифрование включено")
else:
    logger.warning("ENCRYPTION_KEY не задан - токены хранятся открыто")


def encrypt_token(plaintext: str | None) -> str | None:
    """Шифрует строку для хранения в БД. Без ключа - возвращает как есть."""
    if not plaintext:
        return plaintext
    if not _fernet:
        return plaintext
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str | None) -> str | None:
    """Расшифровывает строку из БД."""
    if not ciphertext:
        return ciphertext
    if not _fernet:
        return ciphertext
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # токен сохранен до включения шифрования - отдаем как есть
        logger.debug("Токен не расшифрован, возвращаем как есть")
        return ciphertext
