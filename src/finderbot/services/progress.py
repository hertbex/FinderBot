"""Прогресс-сообщение: троттлинг-редактирование одного Telegram-сообщения."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

log = logging.getLogger(__name__)

MIN_EDIT_INTERVAL = 4.0  # лимит Telegram на изменения ~раз в секунду; держим запас


class Progress:
    """Редактирует одно сообщение не чаще раза в min_interval секунд."""

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        *,
        min_interval: float = MIN_EDIT_INTERVAL,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._message_id = message_id
        self._min_interval = min_interval
        self._last_ts = 0.0
        self._last_text = ""

    async def update(self, text: str, *, force: bool = False) -> bool:
        now = time.monotonic()
        if not force:
            if now - self._last_ts < self._min_interval:
                return False
            if text == self._last_text:
                return False
        try:
            await self._bot.edit_message_text(
                text, chat_id=self._chat_id, message_id=self._message_id
            )
        except TelegramRetryAfter as exc:
            log.debug("RetryAfter %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 0.5)
            try:
                await self._bot.edit_message_text(
                    text, chat_id=self._chat_id, message_id=self._message_id
                )
            except TelegramBadRequest:
                return False
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return False
            log.debug("edit_message_text отклонён: %s", exc)
            return False
        self._last_ts = time.monotonic()
        self._last_text = text
        return True

    async def finish(self, text: str) -> None:
        await self.update(text, force=True)

    async def fail(self, text: str) -> None:
        await self.update(f"❌ {text}", force=True)


SPINNER_FRAMES = ("⏳", "⌛", "🔎", "⏱", "🎧", "💽")


@asynccontextmanager
async def spinner(
    progress: Progress,
    base_text: str,
    *,
    every: float = 5.0,
    frames: tuple[str, ...] = SPINNER_FRAMES,
) -> AsyncIterator[None]:
    """Пока идёт долгая операция — «анимирует» сообщение точкой-спиннером."""
    stop = asyncio.Event()

    async def run() -> None:
        index = 0
        while not stop.wait(every):
            frame = frames[index % len(frames)]
            index += 1
            text = f"{frame} {base_text}"
            try:
                await progress.update(text, force=True)
            except Exception:  # noqa: BLE001 — анимация не критична
                break

    task = asyncio.create_task(run())
    try:
        yield
    finally:
        stop.set()
        task.cancel()
