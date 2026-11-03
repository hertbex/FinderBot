"""SQLite-хранилище, шифрование и per-user креды."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from finderbot.storage.creds import CredentialService, SlskCreds
from finderbot.storage.crypto import Vault, ensure_fernet
from finderbot.storage.db import Store


class FakeSettings:
    """Минимальный набор методов, مصرفируемых CredentialService/ensure_fernet."""

    def __init__(
        self,
        *,
        data_dir: Any,
        encrypt_key: str | None = None,
        admin_user_id: int | None = None,
        soulseek_user: str | None = None,
        soulseek_pass: str | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.encrypt_key = encrypt_key
        self.admin_user_id = admin_user_id
        self.soulseek_user = soulseek_user
        self.soulseek_pass = soulseek_pass
        self._admin_creds = (soulseek_user, soulseek_pass)

    def is_admin(self, telegram_id: int) -> bool:
        return self.admin_user_id is not None and telegram_id == self.admin_user_id

    def admin_creds(self) -> tuple[str, str] | None:
        if self._admin_creds[0] and self._admin_creds[1]:
            return (self._admin_creds[0], self._admin_creds[1])
        return None


async def test_vault_roundtrip(tmp_path) -> None:
    settings = FakeSettings(data_dir=tmp_path)
    vault = Vault(ensure_fernet(settings))
    token = vault.encrypt("secret-строка")
    assert token != "secret-строка"
    assert vault.decrypt(token) == "secret-строка"

    other = Vault(ensure_fernet(FakeSettings(data_dir=tmp_path / "другая")))
    with pytest.raises(ValueError):
        other.decrypt(token)


async def test_passphrase_key_is_deterministic(tmp_path) -> None:
    first = ensure_fernet(FakeSettings(data_dir=tmp_path, encrypt_key="моя фраза"))
    second = ensure_fernet(FakeSettings(data_dir=tmp_path / "ещё", encrypt_key="моя фраза"))
    payload = Vault(first).encrypt("данные")
    assert Vault(second).decrypt(payload) == "данные"


async def test_store_creds_roundtrip(tmp_path) -> None:
    settings = FakeSettings(data_dir=tmp_path)
    vault = Vault(ensure_fernet(settings))
    store = Store(tmp_path / "db.sqlite")
    await store.connect()

    service = CredentialService(store, vault, settings)
    await service.save(42, SlskCreds(user="alice", password="s3cret"))
    assert await service.has_own(42) is True
    got = await service.get(42)
    assert got == SlskCreds(user="alice", password="s3cret")

    login = await service.describe_login(42)
    assert "alice" in login and "свой" in login

    await service.clear(42)
    assert await service.get(42) is None
    await store.close()


async def test_admin_fallback_creds(tmp_path) -> None:
    settings = FakeSettings(
        data_dir=tmp_path,
        admin_user_id=1,
        soulseek_user="adm",
        soulseek_pass="admpass",
    )
    vault = Vault(ensure_fernet(settings))
    store = Store(tmp_path / "db.sqlite")
    await store.connect()
    service = CredentialService(store, vault, settings)

    assert (await service.get(1)) == SlskCreds(user="adm", password="admpass")
    assert (await service.get(2)) is None
    assert "adm" in await service.describe_login(1)
    await store.close()


async def test_file_cache(tmp_path) -> None:
    store = Store(tmp_path / "db.sqlite")
    await store.connect()
    sha = hashlib.sha256("файл".encode()).hexdigest()
    await store.cache_file(sha, "audio", "AUDIO_FILE_ID", title="Song", performer="DJ")
    row = await store.lookup_file(sha)
    assert row is not None
    assert row["file_id"] == "AUDIO_FILE_ID"
    assert row["kind"] == "audio"
    assert row["title"] == "Song"
    assert row["performer"] == "DJ"
    await store.close()
