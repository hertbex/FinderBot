"""Видео: ссылка → очередь → yt-dlp → сжатие под 50 МБ → sendVideo (или аудио)."""

from __future__ import annotations

import html as _html
import logging
from collections import OrderedDict
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from finderbot.config import Settings
from finderbot.routers.candidates import VideoOption, VideoOptionRegistry
from finderbot.services.progress import Progress
from finderbot.services.queue import Job, QueueFull, QueueManager
from finderbot.services.sender import Sender
from finderbot.storage.db import Store
from finderbot.tools.ffmpeg import compress_video, make_video_thumb
from finderbot.tools.paths import ToolPaths
from finderbot.tools.videoplan import audio_bitrate, plan_video
from finderbot.tools.ytdlp import YtDlp
from finderbot.utils.formatting import human_duration, human_size, truncate
from finderbot.utils.urls import extract_url, is_allowed_url

log = logging.getLogger(__name__)
router = Router(name="video")

CALLBACK_PREFIX = "va"


class UrlFileCache:
    """Сопоставление url → sha256 файла, чтобы повторные ссылки не качались."""

    TTL_ITEMS = 500

    def __init__(self) -> None:
        self._items: OrderedDict[str, str] = OrderedDict()

    def add(self, url: str, sha256: str) -> None:
        self._items[url] = sha256
        self._items.move_to_end(url)
        while len(self._items) > self.TTL_ITEMS:
            self._items.popitem(last=False)

    def get(self, url: str) -> str | None:
        sha = self._items.get(url)
        if sha is not None:
            self._items.move_to_end(url)
        return sha


class AllowedUrlFilter(BaseFilter):
    """Текст с URL из разрешённых доменов."""

    async def __call__(self, message: Message, settings: Settings) -> bool | dict[str, str]:
        if message.chat.type != "private" or not message.text:
            return False
        if message.text.startswith("/"):
            return False
        url = extract_url(message.text)
        if not url or not is_allowed_url(url, settings.allowed_hosts):
            return False
        return {"video_url": url}


class DisallowedUrlFilter(BaseFilter):
    """Ссылка на посторонний домен — подсказка про разрешённые."""

    async def __call__(self, message: Message, settings: Settings) -> bool | dict[str, str]:
        if message.chat.type != "private" or not message.text:
            return False
        if message.text.startswith("/"):
            return False
        url = extract_url(message.text)
        if not url or is_allowed_url(url, settings.allowed_hosts):
            return False
        return {"video_url": url}


@router.message(DisallowedUrlFilter())
async def handle_disallowed_url(
    message: Message, video_url: str, settings: Settings
) -> None:
    domains = ", ".join(settings.allowed_hosts)
    await message.answer(
        "🚫 Этот домен не разрешён.\n\n"
        f"Разрешено: <b>{_html.escape(domains)}</b>.\n"
        "Расширить список может владелец бота (ALLOWED_HOSTS в .env)."
    )


@router.message(AllowedUrlFilter())
async def handle_video_url(
    message: Message,
    video_url: str,
    settings: Settings,
    sender: Sender,
    queue: QueueManager,
    url_cache: UrlFileCache,
    ytdlp: YtDlp,
    store: Store,
) -> None:
    url = video_url
    # Мгновенный повтор из кэша: если этот URL уже отправляли — репостим file_id.
    sha = url_cache.get(url)
    if sha:
        row = await store.lookup_file(sha)
        if row and row.get("file_id") and row.get("kind") == "video":
            sent = await sender.send_video_by_id(
                message.chat.id, row["file_id"], reply_to=message.message_id
            )
            if sent is not None:
                try:
                    await message.answer("⚡️ Уже есть на сервере — репост без загрузки.")
                except Exception:  # noqa: BLE001
                    pass
                log.info("Видео из кэша: %s", url)
                return

    note = await message.answer("🎬 Задача принята. Проверю источники…")
    try:
        job = await queue.submit(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            message_id=note.message_id,
            kind="video",
            label=truncate(url, 48),
            payload={"url": url},
        )
    except QueueFull as exc:
        await note.edit_text(f"⏳ {exc}")
        return
    log.info("Видео в очереди: #%s %s", job.seq, url)


@router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
async def handle_video_option(
    cb: CallbackQuery,
    videos: VideoOptionRegistry,
    queue: QueueManager,
) -> None:
    message = cb.message
    if message is None or cb.from_user is None or not cb.data:
        try:
            await cb.answer()
        except Exception:  # noqa: BLE001
            pass
        return
    chat_id, message_id = message.chat.id, message.message_id
    option = videos.get(chat_id, message_id)
    if option is None:
        await answer_alert(cb, "Кнопка устарела — пришлите ссылку заново.")
        return
    if option.user_id != cb.from_user.id:
        await answer_alert(cb, "Это не ваша задача.")
        return

    action = cb.data.removeprefix(f"{CALLBACK_PREFIX}:")
    if action == "no":
        try:
            await message.edit_text("🚫 Отправка аудио отменена.")
        except Exception:  # noqa: BLE001
            log.exception("Не удалось отредактировать сообщение")
        return
    if action != "yes":
        return

    kbps = audio_bitrate(option.duration)
    try:
        await queue.submit(
            user_id=option.user_id,
            chat_id=chat_id,
            message_id=message_id,
            kind="video_audio",
            label=truncate(option.title, 40),
            payload={
                "url": option.url,
                "title": option.title,
                "duration": option.duration,
                "kbps": kbps,
            },
        )
    except QueueFull as exc:
        await answer_alert(cb, str(exc))
        return
    try:
        await message.edit_text(
            f"🎧 В очереди: аудио из «{_html.escape(truncate(option.title, 40))}»"
        )
        await cb.answer("✅ Задача принята")
    except Exception:  # noqa: BLE001
        log.exception("Не удалось подтвердить аудио-задачу")


async def answer_alert(cb: CallbackQuery, text: str) -> None:
    try:
        await cb.answer(text, show_alert=True)
    except Exception:  # noqa: BLE001
        log.debug("Не удалось ответить на callback", exc_info=True)


def make_video_runner(
    *,
    bot: Bot,
    ytdlp: YtDlp,
    sender: Sender,
    settings: Settings,
    tools: ToolPaths,
    videos: VideoOptionRegistry,
    url_cache: UrlFileCache,
):
    """Два пайплайна: run_video (качааем видео) и run_video_audio (только аудио)."""

    def _dir(job: Job) -> Path:
        directory = Path(settings.download_dir) / f"job-{job.seq}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    async def _cleanup(job: Job, directory: Path) -> None:
        if settings.keep_files:
            return
        for leftover in directory.iterdir():
            try:
                leftover.unlink()
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass

    async def _offer_audio(job: Job, info, duration: int | None) -> None:
        option = VideoOption(
            user_id=job.user_id,
            url=job.payload["url"],
            duration=duration,
            title=info.title,
        )
        videos.put(job.chat_id, job.message_id, option)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🎧 Да, аудио", callback_data=f"{CALLBACK_PREFIX}:yes"),
                    InlineKeyboardButton(text="❌ Не надо", callback_data=f"{CALLBACK_PREFIX}:no"),
                ]
            ]
        )
        text = (
            "🎬 Видео длинное и не влезет в лимит 50 МБ даже сжатием.\n"
            f"«{_html.escape(truncate(info.title, 60))}»"
            + (f" · {human_duration(duration)}" if duration else "")
            + "\nОтправить только аудиодорожку (mp3)?"
        )
        try:
            await bot.edit_message_text(
                text,
                chat_id=job.chat_id,
                message_id=job.message_id,
                reply_markup=keyboard,
            )
        except Exception:  # noqa: BLE001
            log.exception("Не удалось предложить аудио-путь")

    async def run_video(job: Job, progress: Progress) -> None:
        url = job.payload["url"]
        info = await ytdlp.probe(url)  # YtDlpError → QueueManager напишет пользователю
        duration = info.duration
        plan = plan_video(duration, settings.max_file_mb)
        if plan.kind == "reject":
            raise RuntimeError(plan.reason or "Видео не влезает в лимит Telegram.")
        if plan.kind == "audio":
            await _offer_audio(job, info, duration)
            return
        if duration and duration > settings.max_video_minutes * 60:
            raise RuntimeError(
                f"Видео длиннее {settings.max_video_minutes} минут — не отправить."
            )

        directory = _dir(job)
        header = f"🎬 Качаю «{_html.escape(truncate(info.title, 40))}»"
        await progress.update(f"{header} — до {plan.height or 1080}p…")
        path = await ytdlp.download(
            url,
            directory,
            mode="video",
            max_height=plan.height,
            on_progress=lambda pct, eta: progress.update(
                header
                + f"\n⬇ {pct:.0f}%"
                + (f" · осталось ~{_html.escape(human_duration(eta))}" if eta else "")
            ),
        )

        if path.stat().st_size > settings.max_file_mb * 1024 * 1024:
            await progress.update("🗜 Файл больше лимита — сжимаю (это небыстро)…")
            compressed = await compress_video(
                tools.ffmpeg,
                path,
                directory / "compressed.mp4",
                max_mb=settings.max_file_mb,
                duration=duration or 600,
                target_height=720,
                ffprobe=tools.ffprobe,
                on_progress=lambda pct, _eta: progress.update(f"🗜 Сжимаю: {pct:.0f}%"),
            )
            path.unlink(missing_ok=True)
            path = compressed
        if path.stat().st_size > settings.max_file_mb * 1024 * 1024:
            raise VideoTooBig(
                "Даже после сжатия файл больше 48 МБ — очень длинное видео. "
                "Могу отправить только аудио: пришлите ссылку снова."
            )

        thumb = await make_video_thumb(tools.ffmpeg, path, directory / "thumb.jpg")
        caption = f"🎬 {_html.escape(truncate(info.title, 90))}"
        if info.uploader:
            caption += f"\n👤 {_html.escape(info.uploader)}"
        if duration:
            caption += f"\n⏱ {human_duration(duration)}"
        size_after = path.stat().st_size
        file_sha = await Sender.sha256(path)
        await sender.send_video(
            job.chat_id,
            path,
            thumb=thumb,
            caption=caption,
            duration=duration,
            reply_to=job.message_id,
        )
        url_cache.add(url, file_sha)
        await progress.finish(
            f"✅ Видео отправлено ({human_size(size_after)})"
        )
        await _cleanup(job, directory)

    async def run_video_audio(job: Job, progress: Progress) -> None:
        url = job.payload["url"]
        title = job.payload.get("title") or url
        duration = job.payload.get("duration")
        kbps = int(job.payload.get("kbps") or 192)
        directory = _dir(job)
        await progress.update("🎧 Извлекаю аудио (mp3)…")
        path = await ytdlp.download(
            url,
            directory,
            mode="audio",
            audio_kbps=kbps,
            on_progress=lambda pct, _eta: progress.update(f"🎧 Аудио: {pct:.0f}%"),
        )
        caption = (
            f"🎧 {_html.escape(truncate(title, 90))}"
            + (f"\n⏱ {human_duration(duration)}" if duration else "")
        )
        await sender.send_audio(
            job.chat_id,
            path,
            title=truncate(title, 90),
            duration=duration,
            caption=caption,
            reply_to=job.message_id,
        )
        await progress.finish(f"✅ Аудио отправлено ({kbps} kbps)")
        await _cleanup(job, directory)

    return run_video, run_video_audio


class VideoTooBig(RuntimeError):
    """Сжатие не помогло."""
