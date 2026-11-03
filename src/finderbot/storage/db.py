"""SQLite-хранилище: пользователи (шифрованные Soulseek-креды) и кэш file_id."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    slsk_user   TEXT,
    slsk_pass   TEXT
);
CREATE TABLE IF NOT EXISTS file_cache (
    sha256     TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    file_id    TEXT NOT NULL,
    title      TEXT,
    performer  TEXT,
    duration   INTEGER,
    thumb_id   TEXT,
    created_at TEXT NOT NULL
);
"""

_NOW = (
    "INSERT INTO users (telegram_id, created_at) VALUES (:id, :now) "
    "ON CONFLICT(telegram_id) DO NOTHING"
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    """Обёртка над aiosqlite. Поднимается один раз на старте приложения."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        log.info("SQLite открыт: %s", self.path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
            log.info("SQLite закрыт")

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store.connect() не вызван")
        return self._db

    # --- пользователи ------------------------------------------------------

    async def ensure_user(self, telegram_id: int) -> None:
        await self.db.execute(_NOW, {"id": telegram_id, "now": _now()})
        await self.db.commit()

    async def set_soulseek_tokens(
        self, telegram_id: int, user_token: str, pass_token: str
    ) -> None:
        await self.db.execute(
            "INSERT INTO users (telegram_id, created_at, slsk_user, slsk_pass) "
            "VALUES (:id, :now, :user, :pass) "
            "ON CONFLICT(telegram_id) DO UPDATE SET "
            "slsk_user = excluded.slsk_user, slsk_pass = excluded.slsk_pass",
            {
                "id": telegram_id,
                "now": _now(),
                "user": user_token,
                "pass": pass_token,
            },
        )
        await self.db.commit()

    async def clear_soulseek_tokens(self, telegram_id: int) -> None:
        await self.db.execute(
            "UPDATE users SET slsk_user = NULL, slsk_pass = NULL WHERE telegram_id = :id",
            {"id": telegram_id},
        )
        await self.db.commit()

    async def get_soulseek_tokens(self, telegram_id: int) -> tuple[str, str] | None:
        async with self.db.execute(
            "SELECT slsk_user, slsk_pass FROM users WHERE telegram_id = :id",
            {"id": telegram_id},
        ) as cursor:
            row = await cursor.fetchone()
        if row and row["slsk_user"] and row["slsk_pass"]:
            return (row["slsk_user"], row["slsk_pass"])
        return None

    async def count_users(self) -> int:
        async with self.db.execute("SELECT COUNT(*) AS n FROM users") as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    # --- кэш file_id -------------------------------------------------------

    async def lookup_file(self, sha256: str) -> dict[str, Any] | None:
        async with self.db.execute(
            "SELECT * FROM file_cache WHERE sha256 = :sha", {"sha": sha256}
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def cache_file(
        self,
        sha256: str,
        kind: str,
        file_id: str,
        *,
        title: str | None = None,
        performer: str | None = None,
        duration: int | None = None,
        thumb_id: str | None = None,
    ) -> None:
        await self.db.execute(
            "INSERT INTO file_cache "
            "(sha256, kind, file_id, title, performer, duration, thumb_id, created_at) "
            "VALUES (:sha, :kind, :file_id, :title, :performer, :duration, :thumb, :now) "
            "ON CONFLICT(sha256) DO UPDATE SET file_id = excluded.file_id, "
            "thumb_id = excluded.thumb_id",
            {
                "sha": sha256,
                "kind": kind,
                "file_id": file_id,
                "title": title,
                "performer": performer,
                "duration": duration,
                "thumb": thumb_id,
                "now": _now(),
            },
        )
        await self.db.commit()
