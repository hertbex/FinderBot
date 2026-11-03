"""Per-user Soulseek-креды: шифрование + админский fallback (.env)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from finderbot.storage.crypto import Vault
from finderbot.storage.db import Store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlskCreds:
    user: str
    password: str


class CredentialService:
    """Хранит зашифрованные Soulseek-креды пользователей."""

    def __init__(self, store: Store, vault: Vault, settings) -> None:
        self._store = store
        self._vault = vault
        self._settings = settings

    async def get(self, telegram_id: int) -> SlskCreds | None:
        """Креды пользователя, для админа — дефолт из .env."""
        tokens = await self._store.get_soulseek_tokens(telegram_id)
        if tokens:
            try:
                return SlskCreds(
                    user=self._vault.decrypt(tokens[0]),
                    password=self._vault.decrypt(tokens[1]),
                )
            except ValueError as exc:
                log.warning("Креды пользователя %s не расшифровались: %s", telegram_id, exc)
                return None
        if self._settings.is_admin(telegram_id):
            admin = self._settings.admin_creds()
            if admin:
                return SlskCreds(user=admin[0], password=admin[1])
        return None

    async def has_own(self, telegram_id: int) -> bool:
        return (await self._store.get_soulseek_tokens(telegram_id)) is not None

    async def save(self, telegram_id: int, creds: SlskCreds) -> None:
        await self._store.ensure_user(telegram_id)
        await self._store.set_soulseek_tokens(
            telegram_id,
            self._vault.encrypt(creds.user),
            self._vault.encrypt(creds.password),
        )

    async def clear(self, telegram_id: int) -> None:
        await self._store.clear_soulseek_tokens(telegram_id)

    async def describe_login(self, telegram_id: int) -> str:
        """Логин для отображения: свой / админский / нет."""
        tokens = await self._store.get_soulseek_tokens(telegram_id)
        if tokens:
            try:
                return f"{self._vault.decrypt(tokens[0])} (свой аккаунт)"
            except ValueError:
                return "(проблема расшифровки — перелогиньтесь)"
        if self._settings.is_admin(telegram_id) and self._settings.admin_creds():
            return f"{self._settings.soulseek_user} (админский из .env)"
        return "не подключён"
