"""Команды: /start /help /status /cancel."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from finderbot.config import Settings
from finderbot.services.queue import QueueManager
from finderbot.storage.creds import CredentialService

router = Router(name="start")

WELCOME = (
    "👋 Привет! Это <b>FinderBot</b>.\n\n"
    "Что я умею:\n"
    "🎵 <b>Песня по названию</b> — просто пришлите текст «артист - трек», "
    "я найду и отдам файл с Soulseek (нужен ваш аккаунт: /login).\n"
    "🎬 <b>Видео по ссылке</b> — ссылка на YouTube / TikTok / Instagram, "
    "лучший вариант до лимита Telegram (50 МБ).\n\n"
    "Команды: /help · /login · /me · /status · /cancel"
)

HELP = (
    "<b>Как пользоваться</b>\n\n"
    "🎵 Песня: пришлите обычным сообщением: <code>Daft Punk - Get Lucky</code>.\n"
    "Появится список найденных вариантов — выберите кнопкой, я скачаю и пришлю mp3/flac.\n\n"
    "🎬 Видео: пришлите ссылку: <code>https://youtu.be/…</code>.\n"
    "Я скачаю лучший по качеству вариант, умяну под лимит 50 МБ (или предложу аудио).\n\n"
    f"Лимиты: {Settings.model_fields['requests_per_minute'].default} запроса/мин, "
    f"{Settings.model_fields['queue_per_user'].default} задачи в очереди на пользователя.\n\n"
    "🔐 <b>/login</b> — свой Soulseek-аккаунт (нужен для песен!). Логин/пароль "
    "сразу удаляются из чата и хранятся зашифрованными.\n"
    "ℹ️ <b>/me</b> — какой аккаунт подключён · <b>/logout</b> — отвязать\n"
    "⏳ <b>/status</b> — очередь · <b>/cancel</b> — отменить свои задачи"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    settings: Settings,
    queue: QueueManager,
    credentials: CredentialService,
    store,  # Store
) -> None:
    user_id = message.from_user.id  # private-only гарантируется middleware
    lines: list[str] = ["<b>Статус</b>"]
    personal = queue.describe_user(user_id)
    lines.append("👥 Ваши задачи:")
    lines.append(f"· {personal}" if personal else "· нет активных задач")
    stats = queue.stats()
    lines.append(
        "\n🌐 Бот: воркеров {w}, выполняется {r}, в очереди {q}".format(
            **stats
        )
    )
    login = await credentials.describe_login(user_id)
    lines.append(f"🔑 Soulseek: {login}")
    await message.answer("\n".join(lines))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, queue: QueueManager) -> None:
    canceled = await queue.cancel_user(message.from_user.id)
    has_state = await state.get_state() is not None
    if has_state:
        await state.clear()
    if canceled or has_state:
        parts = []
        if canceled:
            parts.append("задачи отменены")
        if has_state:
            parts.append("ввод отменён")
        await message.answer(f"🚫 {'; '.join(parts).capitalize()}.")
    else:
        await message.answer("🤔 Нечего отменять.")


@router.message(Command("stop"))
async def cmd_stop(message: Message, queue: QueueManager) -> None:
    await queue.cancel_user(message.from_user.id)
    await message.answer("🚫 Отправлена отмена задач.")
