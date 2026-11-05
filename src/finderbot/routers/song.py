"""Музыка: текст → многофазный sockseek-поиск (STO) → отбор → кнопки → queue → sendAudio
Конвейер портирован из StreamToOffline: CandidateSelector (качество/длительность/
версии) + STO-ранжирование. Лучший кандидат помечается ⭐.
"""

from __future__ import annotations

import asyncio
import html as _html
import logging
import re
from dataclasses import asdict
from pathlib import Path

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from finderbot.config import Settings
from finderbot.routers.candidates import CandidateEntry, CandidateRegistry
from finderbot.services.progress import Progress, spinner
from finderbot.services.queue import Job, QueueFull, QueueManager
from finderbot.services.sender import Sender
from finderbot.storage.creds import CredentialService
from finderbot.tools.ffmpeg import cover_image
from finderbot.tools.paths import ToolPaths
from finderbot.tools.sockseek import (
    SearchFlags,
    SlskResult,
    SockseekClient,
    SockseekError,
    SockseekTimeout,
)
from finderbot.tools.songselect import CandidateSelector, SelectionPolicy
from finderbot.utils.formatting import human_duration, human_size, parse_track_name, truncate
from finderbot.utils.urls import extract_url

log = logging.getLogger(__name__)
router = Router(name="song")

PAGE_SIZE = 8
MAX_CANDIDATES = 40
CALLBACK_PREFIX = "sl"

SELECTOR = CandidateSelector()

_INVALID_PATH_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


async def _safe_delete(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:  # noqa: BLE001
        log.debug("Не удалось удалить сообщение", exc_info=True)


async def _answer(cb: CallbackQuery, text: str, *, alert: bool = False) -> None:
    try:
        await cb.answer(text, show_alert=alert)
    except Exception:  # noqa: BLE001
        log.debug("Не удалось ответить на callback", exc_info=True)


def _bitrate_tag(result: SlskResult) -> str:
    if result.bitrate:
        return f"{result.bitrate}k"
    return "lossless" if result.ext in {"flac", "wav", "ape", "alac", "dsf", "wv"} else result.ext


def _candidate_label(index: int, result: SlskResult, *, star: bool = False) -> str:
    prefix = "⭐ " if star else ""
    return f"{prefix}{index + 1}. {result.ext} {_bitrate_tag(result)[:14]}"


def _candidate_line(index: int, result: SlskResult, *, star: bool = False) -> str:
    peer = _html.escape(truncate(result.peer, 16))
    prefix = "⭐ " if star else ""
    return (
        f"{prefix}{index + 1}. {peer} · {result.ext.upper()} {_bitrate_tag(result)} · "
        f"{human_size(result.size)}"
    )


def _keyboard(entry: CandidateEntry) -> InlineKeyboardMarkup:
    start = entry.page * PAGE_SIZE
    visible = entry.candidates[start : start + PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    for pair_start in range(0, len(visible), 2):
        pair = visible[pair_start : pair_start + 2]
        row = [
            InlineKeyboardButton(
                text=_candidate_label(
                    start + pair_start + offset,
                    result,
                    star=(start + pair_start + offset == 0 and entry.star_first),
                ),
                callback_data=f"{CALLBACK_PREFIX}:{start + pair_start + offset}",
            )
            for offset, result in enumerate(pair)
        ]
        rows.append(row)
    nav: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="✖ Закрыть", callback_data=f"{CALLBACK_PREFIX}:x")
    ]
    if start + PAGE_SIZE < len(entry.candidates):
        nav.append(InlineKeyboardButton(text="→ Ещё", callback_data=f"{CALLBACK_PREFIX}:more"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render(bot, chat_id: int, message_id: int, entry: CandidateEntry) -> None:
    start = entry.page * PAGE_SIZE
    visible = entry.candidates[start : start + PAGE_SIZE]
    head = f"🔎 «{_html.escape(truncate(entry.query, 40))}»"
    if entry.header_note:
        head += "\n<i>" + entry.header_note + "</i>"
    listing = "\n".join(
        _candidate_line(
            i, result, star=(entry.star_first and i == 0)
        )
        for i, result in enumerate(visible)
    )
    footer = f"\n<i>{start + 1}–{start + len(visible)} из {len(entry.candidates)}</i>"
    text = f"{head}\n{listing}{footer}"
    try:
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=_keyboard(entry),
        )
    except Exception:  # noqa: BLE001
        log.exception("Не удалось отрисовать список")


def _note_for(report, spec) -> str:
    """Строка отчёта для шапки: найдено/подходит/отсекло + эталон длительности."""
    length_note = ""
    if spec.reference_duration:
        length_note = f"⏱ ~{human_duration(spec.reference_duration)} · "
    return f"{length_note}найдено {report.total}, подходит {report.eligible}; {report.summary()}"


@router.message(F.text)
async def handle_song_query(
    message: Message,
    settings: Settings,
    credentials: CredentialService,
    candidates: CandidateRegistry,
    sockseek: SockseekClient,
) -> None:
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return
    if extract_url(text) is not None:
        return  # ссылки ведёт видео-роутер
    user_id = message.from_user.id
    creds = await credentials.get(user_id)
    if creds is None:
        await message.answer(
            "🔐 Для поиска песен нужен Soulseek-логин.\n"
            "<b>/login</b> — подключить. Аккаунт можно создать на slsknet.org, "
            "если у вас его нет."
        )
        return

    query = text[:160]
    status = await message.answer(
        f"⏳ Ищу «{_html.escape(truncate(query, 60))}» в Soulseek…"
    )
    progress = Progress(message.bot, message.chat.id, status.message_id)
    search_flags = SearchFlags(
        formats=settings.slsk_formats or None,
        min_bitrate_kbps=settings.slsk_min_bitrate,
        length_tolerance_seconds=settings.slsk_length_tolerance_sec,
    )
    try:
        async with spinner(progress, f"Ищу «{_html.escape(truncate(query, 40))}»"):
            results, spec = await sockseek.search(creds, query, flags=search_flags)
    except SockseekTimeout as exc:
        await progress.fail(str(exc))
        return
    except SockseekError as exc:
        await progress.fail(str(exc))
        return

    if not results:
        hint = (
            "Запрос без распознавания «артист - title» — попробовали каскад "
            "artist=/title=/свободный текст."
            if not spec.artist or not spec.title
            else ""
        )
        await progress.finish(
            "😕 Ничего не нашлось. " + hint + "Проверьте /login и переформулируйте: "
            "«артист - трек» (можно с длительностью: «(3:45)»)."
        )
        return

    policy = SelectionPolicy(
        min_bitrate_kbps=settings.slsk_min_bitrate,
        version_policy=settings.slsk_version_policy,
        length_tolerance_seconds=settings.slsk_length_tolerance_sec,
        max_size_bytes=settings.max_file_mb * 1024 * 1024,
    )
    eligible, report = SELECTOR.rank(results, spec, policy)

    if eligible:
        chosen = eligible[:MAX_CANDIDATES]
        entry = candidates.put(
            message.chat.id,
            status.message_id,
            user_id=user_id,
            query=(spec.artist and spec.title and f"{spec.artist} - {spec.title}") or spec.raw,
            candidates=chosen,
            star_first=True,
            header_note=_html.escape(_note_for(report, spec)),
        )
        await progress.update(
            f"🔍 {_html.escape(str(report.total))}·подходит {report.eligible}"
        )
        await _render(message.bot, message.chat.id, status.message_id, entry)
        return

    # STO-фильтры выжили всех: показываем сырую выдачу, отранжированную как STO
    ranked = sorted(results, key=lambda r: SELECTOR._rank(r, spec), reverse=True)  # noqa: SLF001
    del ranked[MAX_CANDIDATES:]
    note = (
        f"⚠️ фильтры отбросили все {report.total} кандидата(ов) — "
        f"{_html.escape(report.summary())}"
    )
    entry = candidates.put(
        message.chat.id,
        status.message_id,
        user_id=user_id,
        query=(spec.artist and spec.title and f"{spec.artist} - {spec.title}") or spec.raw,
        candidates=ranked,
        star_first=False,
        header_note=note,
    )
    await progress.update(f"⚠️ подходит 0 из {report.total} — показываю всё")
    await _render(message.bot, message.chat.id, status.message_id, entry)


@router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
async def handle_candidate(
    cb: CallbackQuery,
    settings: Settings,
    credentials: CredentialService,
    candidates: CandidateRegistry,
    queue: QueueManager,
) -> None:
    message = cb.message
    if message is None or cb.from_user is None:
        await _answer(cb)
        return
    chat_id, message_id = message.chat.id, message.message_id
    entry = candidates.get(chat_id, message_id)
    if entry is None:
        await _answer(cb, "Список устарел — пришлите запрос заново.", alert=True)
        return
    if entry.user_id != cb.from_user.id:
        await _answer(cb, "Это не ваш список.", alert=True)
        return

    action = cb.data.removeprefix(f"{CALLBACK_PREFIX}:") if cb.data else ""
    if action == "x":
        candidates.drop(chat_id, message_id)
        await _safe_delete(message.bot, chat_id, message_id)
        await _answer(cb)
        return
    if action == "more":
        entry.page += 1
        candidates.update_page(chat_id, message_id, entry.page)
        await _render(message.bot, chat_id, message_id, entry)
        await _answer(cb)
        return

    if not action.isdigit():
        await _answer(cb)
        return
    index = int(action)
    if not (0 <= index < len(entry.candidates)):
        await _answer(cb, "Такого варианта уже нет.", alert=True)
        return

    result = entry.candidates[index]
    creds = await credentials.get(entry.user_id)
    if creds is None:
        await _answer(cb, "Аккаунт отключился — используйте /login.", alert=True)
        return

    label = f"{truncate(entry.query, 32)} · {result.ext}"
    try:
        job = await queue.submit(
            user_id=entry.user_id,
            chat_id=chat_id,
            message_id=message_id,
            kind="song",
            label=label,
            payload={"result": asdict(result), "query": entry.query},
        )
    except QueueFull as exc:
        await _answer(cb, str(exc), alert=True)
        return
    await _answer(cb, "✅ Ушло в загрузку")
    try:
        await message.edit_text(
            f"⬇️ В очереди: {_html.escape(label)} (задача #{job.seq})"
        )
    except Exception:  # noqa: BLE001
        log.exception("Не удалось обновить сообщение")


# --- фоновое скачивание ------------------------------------------------------


def _sanitize_name(name: str) -> str:
    return _INVALID_PATH_RE.sub(" ", name).strip()[:90] or "unknown"


def make_song_runner(
    *,
    sockseek: SockseekClient,
    sender: Sender,
    settings: Settings,
    tools: ToolPaths,
    credentials: CredentialService,
):
    """Фоновая задача: скачать выбранного кандидата и отправить аудио."""

    async def _tick(progress: Progress, base: str, every: float = 5.0) -> None:
        while True:
            await asyncio.sleep(every)
            await progress.update(base)

    async def run_song(job: Job, progress: Progress) -> None:
        result = SlskResult(**job.payload["result"])
        query = job.payload.get("query") or result.filename
        artist, title = parse_track_name(query)
        display_title = f"{artist} - {title}" if artist and title else (title or result.filename)
        work_dir = Path(settings.download_dir) / f"job-{job.seq}"
        work_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = _sanitize_name(display_title)
        destination = work_dir / f"{safe_stem}.{result.ext}"

        creds = await credentials.get(job.user_id)
        if creds is None:
            raise RuntimeError("Аккаунт Soulseek отключён — используйте /login")

        size = human_size(result.size)
        base_text = (
            f"⬇️ Качаю {_html.escape(result.ext.upper())} {_bitrate_tag(result)} · {size} · "
            f"peer {_html.escape(truncate(result.peer, 12))}…"
        )
        await progress.update(base_text)
        ticker = asyncio.create_task(_tick(progress, base_text))
        try:
            path = await sockseek.download(creds, result, destination)
        except SockseekError as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            ticker.cancel()

        cover = await cover_image(tools.ffmpeg, path, work_dir / "cover.jpg")
        kbps_part = f" · {_bitrate_tag(result)}" if result.bitrate else " · lossless"
        caption = (
            f"🎧 <b>{_html.escape(display_title)}</b>\n"
            f"👤 {_html.escape(truncate(result.peer, 16))} · {result.ext.upper()}"
            f"{kbps_part} · {human_size(result.size)}"
        )
        await sender.send_audio(
            job.chat_id,
            path,
            title=display_title,
            performer=artist if artist else None,
            duration=result.length,
            thumb=cover,
            caption=caption,
            reply_to=job.message_id,
        )
        await progress.finish(f"✅ Отправлено: {_html.escape(display_title)}")
        if not settings.keep_files:
            try:
                for leftover in work_dir.iterdir():
                    leftover.unlink(missing_ok=True)
                work_dir.rmdir()
            except OSError:
                log.debug("Не удалось очистить work-dir", exc_info=True)

    return run_song
