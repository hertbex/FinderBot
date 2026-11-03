"""Шифрование секретов (Fernet): ключ из настроек или автосозданный файл."""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


class Vault:
    """Шифрует/расшифровывает строки Fernet-токенами."""

    def __init__(self, fernet: Fernet) -> None:
        self._fernet = fernet

    def encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "Не удалось расшифровать секрет — сменился ключ шифрования "
                "(ENCRYPT_KEY/secret.key). Пользователям нужно перелогиниться (/login)."
            ) from exc


def ensure_fernet(settings) -> Fernet:
    """Fernet из settings.encrypt_key; иначе персистентный data/secret.key."""
    if settings.encrypt_key:
        return Fernet(_key_from_secret(settings.encrypt_key))
    key_file = Path(settings.data_dir) / "secret.key"
    if key_file.exists():
        return Fernet(_key_from_secret(key_file.read_text(encoding="utf-8")))
    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key.decode("ascii"), encoding="utf-8")
    log.info("Создан ключ шифрования: %s (не удаляйте: иначе /login заново)", key_file)
    return Fernet(key)


def _key_from_secret(secret: str) -> bytes:
    """Принимает и валидный Fernet-ключ, и произвольную фразу-пароль."""
    raw = secret.strip().encode("utf-8")
    try:
        Fernet(raw)  # проверка валидности как Fernet-ключа
        return raw
    except Exception:  # noqa: BLE001 — иначе трактуем как passphrase
        derived = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(derived)
