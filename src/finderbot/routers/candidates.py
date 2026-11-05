"""Реестры для inline-клавиатур: candidates музыку «номер → кандидат» и видео-опции."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from finderbot.tools.sockseek import SlskResult


@dataclass
class CandidateEntry:
    user_id: int
    query: str
    candidates: list[SlskResult]
    page: int = 0
    star_first: bool = False          # пометить первый (лучший у STO) звездой
    header_note: str = ""             # отчёт селектора: «найдено N · подходящих M…»
    created_at: float = field(default_factory=time.monotonic)


class CandidateRegistry:
    """In-memory связка «сообщение с кнопками → список кандидатов» (TTL 30 минут)."""

    TTL = 30 * 60
    MAX_ENTRIES = 200

    def __init__(self) -> None:
        self._entries: dict[tuple[int, int], CandidateEntry] = {}

    def put(
        self,
        chat_id: int,
        message_id: int,
        *,
        user_id: int,
        query: str,
        candidates: list[SlskResult],
        star_first: bool = False,
        header_note: str = "",
    ) -> CandidateEntry:
        key = (chat_id, message_id)
        entry = CandidateEntry(
            user_id=user_id,
            query=query,
            candidates=candidates,
            star_first=star_first,
            header_note=header_note,
        )
        self._entries[key] = entry
        self._evict(len(self._entries) > self.MAX_ENTRIES)
        return entry

    def get(self, chat_id: int, message_id: int) -> CandidateEntry | None:
        entry = self._entries.get((chat_id, message_id))
        if entry is None:
            return None
        if time.monotonic() - entry.created_at > self.TTL:
            self._entries.pop((chat_id, message_id), None)
            return None
        return entry

    def update_page(self, chat_id: int, message_id: int, page: int) -> None:
        entry = self.get(chat_id, message_id)
        if entry is not None:
            entry.page = page

    def drop(self, chat_id: int, message_id: int) -> None:
        self._entries.pop((chat_id, message_id), None)

    def _evict(self, force: bool) -> None:
        if not force:
            return
        now = time.monotonic()
        expired = [key for key, entry in self._entries.items() if now - entry.created_at > self.TTL]
        for key in expired[: max(0, len(self._entries) - self.MAX_ENTRIES + len(expired))]:
            self._entries.pop(key, None)


@dataclass
class VideoOption:
    """Контекст кнопок «отправить как аудио» при не влезающем видео."""

    user_id: int
    url: str
    duration: int | None
    title: str
    created_at: float = field(default_factory=time.monotonic)


class VideoOptionRegistry:
    """Связка «сообщение → url/duration» для fallback-аудио."""

    TTL = 30 * 60
    MAX_ENTRIES = 100

    def __init__(self) -> None:
        self._entries: dict[tuple[int, int], VideoOption] = {}

    def put(self, chat_id: int, message_id: int, option: VideoOption) -> None:
        self._entries[(chat_id, message_id)] = option
        self._evict()

    def get(self, chat_id: int, message_id: int) -> VideoOption | None:
        entry = self._entries.get((chat_id, message_id))
        if entry is None:
            return None
        if time.monotonic() - entry.created_at > self.TTL:
            self._entries.pop((chat_id, message_id), None)
            return None
        return entry

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [key for key, entry in self._entries.items() if now - entry.created_at > self.TTL]
        for key in expired:
            self._entries.pop(key, None)
