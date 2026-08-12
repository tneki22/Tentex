from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.projects.errors import ProjectDomainError


def _installation_key(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes().strip()
    with os.fdopen(descriptor, "wb") as output:
        output.write(key)
    with suppress(OSError):
        path.chmod(0o600)
    return key


def _fernet() -> Fernet:
    raw = (
        settings.secret_key.encode()
        if settings.secret_key
        else _installation_key(settings.installation_secret_path)
    )
    try:
        return Fernet(raw)
    except (TypeError, ValueError) as error:
        raise ProjectDomainError(
            "Ключ шифрования установки имеет неверный формат",
            status=500,
            code="ai_secret_invalid",
        ) from error


def encrypt_secret(plain: str) -> bytes:
    if not plain:
        raise ProjectDomainError(
            "Пустой ключ провайдера нельзя сохранить",
            status=422,
            code="ai_credentials_empty",
        )
    return _fernet().encrypt(plain.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as error:
        raise ProjectDomainError(
            "Не удалось расшифровать ключ провайдера этой установки",
            status=500,
            code="ai_secret_mismatch",
        ) from error
