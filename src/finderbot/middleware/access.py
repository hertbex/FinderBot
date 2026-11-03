"""Доступ: только личные чаты + простейший рейт-лимит."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Update

log = logging.getLogger(__name__)


class PrivateOnlyMiddleware(BaseMiddleware):
    """В группах бот не работает: команды отвечают подсказкой, остальное молчит."""

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        message = event.message if isinstance(event, Update) else None
        if message is None:
            return await handler(event, data)
        chat_type = message.chat.type
        if chat_type == "private":
            return await handler(event, data)
        # Не для нас: в группах отвечаем только на команды, остальное молча.
        text = message.text or message.caption or ""
        if text.startswith("/"):
            try:
                await message.answer(
                    "🤝 Я работаю только в личных сообщениях. Напишите /start в ЛС."
                )
            except Exception:  # noqa: BLE001
                log.debug("Не удалось ответить в групповом чате", exc_info=True)
        return None


class RateLimitMiddleware(BaseMiddleware):
    """N сообщений в минуту на пользователя (админ не ограничен)."""

    def __init__(self, per_minute: int, admin_id: int | None = None) -> None:
        self._per_minute = max(1, int(per_minute))
        self._admin = admin_id
        self._hits: dict[int, deque[float]] = {}
        self._last_warn: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update) or event.message is None:
            return await handler(event, data)
        message = event.message
        if message.chat.type != "private" or message.from_user is None:
            return await handler(event, data)
        user_id = message.from_user.id
        if self._admin is not None and user_id == self._admin:
            return await handler(event, data)

        now = time.monotonic()
        window = self._hits.setdefault(user_id, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self._per_minute:
            last = self._last_warn.get(user_id, 0.0)
            if now - last > 30:
                self._last_warn[user_id] = now
                try:
                    await message.answer(f"⏳ Спокойнее: до {self._per_minute} сообщений в минуту.")
                except Exception:  # noqa: BLE001
                    log.debug("Не удалось отправить предупреждение rate-limit", exc_info=True)
            return None
        window.append(now)
        return await handler(event, data)
