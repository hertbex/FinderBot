"""Отправка готовых файлов в Telegram с кэшем file_id и автоочисткой."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from finderbot.storage.db import Store

log = logging.getLogger(__name__)


class Sender:
    """sendAudio/sendVideo: повторная отправка тем же данными берётся из кэша."""

    def __init__(
        self,
        bot: Bot,
        store: Store,
        *,
        downloads_root: Path,
        keep_files: bool = False,
    ) -> None:
        self._bot = bot
        self._store = store
        self._root = Path(downloads_root).resolve()
        self.keep_files = keep_files

    # --- helpers -------------------------------------------------------------

    @staticmethod
    async def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        chunks = 1024 * 1024
        with open(path, "rb") as handle:
            while chunk := await asyncio.to_thread(handle.read, chunks):
                digest.update(chunk)
        return digest.hexdigest()

    def _cleanup(self, path: Path) -> None:
        """Удаляет файл, только если он внутри downloads-root."""
        if self.keep_files or path is None:
            return
        try:
            resolved = Path(path).resolve()
            if resolved.is_relative_to(self._root) and resolved.is_file():
                resolved.unlink()
                log.debug("Удалён файл: %s", resolved)
        except OSError:
            log.debug("Не удалось удалить: %s", path, exc_info=True)

    # --- публичное ------------------------------------------------------------

    async def send_audio(
        self,
        chat_id: int,
        path: Path,
        *,
        title: str | None = None,
        performer: str | None = None,
        duration: int | None = None,
        thumb: Path | None = None,
        caption: str | None = None,
        reply_to: int | None = None,
    ) -> Message | None:
        sha = await self.sha256(path)
        cached = await self._store.lookup_file(sha)

        if cached and cached.get("file_id"):
            try:
                return await self._bot.send_audio(
                    chat_id=chat_id,
                    audio=cached["file_id"],
                    caption=caption,
                    reply_to_message_id=reply_to,
                )
            except Exception:  # noqa: BLE001 — file_id может протухнуть
                log.debug("Кэш file_id недействителен, качаем заново")

        thumb_file = FSInputFile(thumb) if (thumb and thumb.is_file()) else None
        message = await self._bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(path),
            title=title or path.stem,
            performer=performer,
            duration=duration,
            thumbnail=thumb_file,
            caption=caption,
            reply_to_message_id=reply_to,
        )
        if message and message.audio:
            await self._store.cache_file(
                sha,
                "audio",
                message.audio.file_id,
                title=title,
                performer=performer,
                duration=duration,
                thumb_id=(message.audio.thumbnail.file_id if message.audio.thumbnail else None),
            )
        self._cleanup(path)
        if thumb:
            self._cleanup(thumb)
        return message

    async def send_video_by_id(
        self,
        chat_id: int,
        file_id: str,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
    ) -> Message | None:
        """Отправка ранее загруженного видео по file_id (None при протухшем id)."""
        try:
            return await self._bot.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=caption,
                reply_to_message_id=reply_to,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Отправка по кэш-file_id не удалась: %s", exc)
            return None

    async def send_audio_by_id(
        self,
        chat_id: int,
        file_id: str,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
    ) -> Message | None:
        """Отправка ранее загруженного аудио по file_id."""
        try:
            return await self._bot.send_audio(
                chat_id=chat_id,
                audio=file_id,
                caption=caption,
                reply_to_message_id=reply_to,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Отправка аудио по кэш-file_id не удалась: %s", exc)
            return None

    async def send_video(
        self,
        chat_id: int,
        path: Path,
        *,
        thumb: Path | None = None,
        caption: str | None = None,
        duration: int | None = None,
        reply_to: int | None = None,
    ) -> Message | None:
        sha = await self.sha256(path)
        cached = await self._store.lookup_file(sha)

        if cached and cached.get("file_id"):
            try:
                return await self._bot.send_video(
                    chat_id=chat_id,
                    video=cached["file_id"],
                    caption=caption,
                    reply_to_message_id=reply_to,
                )
            except Exception:  # noqa: BLE001
                log.debug("Кэш file_id видео протух — заново")

        thumb_file = FSInputFile(thumb) if (thumb and thumb.is_file()) else None
        message = await self._bot.send_video(
            chat_id=chat_id,
            video=FSInputFile(path),
            thumbnail=thumb_file,
            caption=caption,
            duration=duration,
            reply_to_message_id=reply_to,
        )
        if message and message.video:
            await self._store.cache_file(
                sha,
                "video",
                message.video.file_id,
                duration=duration,
                thumb_id=(message.video.thumbnail.file_id if message.video.thumbnail else None),
            )
        self._cleanup(path)
        if thumb:
            self._cleanup(thumb)
        return message
