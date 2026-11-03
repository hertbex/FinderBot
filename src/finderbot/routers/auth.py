"""FSM-логин в Soulseek (/login /logout /me). Месседжи с паролем удаляются."""

from __future__ import annotations

import html as _escape
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from finderbot.storage.creds import CredentialService, SlskCreds

log = logging.getLogger(__name__)
router = Router(name="auth")


class LoginStates(StatesGroup):
    username = State()
    password = State()


async def _delete_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        log.debug("Не удалось удалить сообщение", exc_info=True)


async def _delete_prompt(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:  # noqa: BLE001
        log.debug("Не удалось удалить prompt", exc_info=True)


async def _cancel_flow(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    for message_id in data.get("prompts", []):
        await _delete_prompt(message.bot, message.chat.id, message_id)
    await _delete_message(message)
    await state.clear()
    await message.answer("🚫 Вход отменён.")


async def _track_prompt(state: FSMContext, message_id: int) -> None:
    data = await state.get_data()
    await state.update_data(prompts=[*(data.get("prompts", []) or []), message_id])


@router.message(Command("login"))
async def cmd_login(
    message: Message, state: FSMContext, credentials: CredentialService
) -> None:
    await _delete_message(message)
    current = await credentials.describe_login(message.from_user.id)
    prompt = await message.answer(
        "🔐 <b>Подключение Soulseek-аккаунта</b>\n\n"
        f"Сейчас подключён: <code>{_escape.escape(current)}</code>\n\n"
        "1️⃣ Пришлите <b>логин</b> (сообщение сразу удалится)."
    )
    await state.set_state(LoginStates.username)
    await state.update_data(prompts=[prompt.message_id])


@router.message(Command("logout"))
async def cmd_logout(
    message: Message, state: FSMContext, credentials: CredentialService
) -> None:
    await state.clear()
    await credentials.clear(message.from_user.id)
    await message.answer("🔓 Аккаунт отключён. Для поиска песен подключите снова: /login")


@router.message(Command("me"))
async def cmd_me(message: Message, credentials: CredentialService) -> None:
    login = await credentials.describe_login(message.from_user.id)
    await message.answer(f"🔑 Soulseek: <code>{_escape.escape(login)}</code>")


@router.message(LoginStates.username, F.text)
async def login_username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    user = (message.text or "").strip()
    if user.startswith("/"):
        await _cancel_flow(message, state)
        return
    if not (3 <= len(user) <= 32):
        prompt = await message.answer("❗️ Логин 3–32 символа. Пришлите снова:")
        await _delete_message(message)
        await _track_prompt(state, prompt.message_id)
        return

    for message_id in data.get("prompts", []):
        await _delete_prompt(message.bot, message.chat.id, message_id)
    await _delete_message(message)

    prompt = await message.answer(
        f"🔑 Логин: <code>{_escape.escape(user)}</code>\n"
        "Теперь <b>пароль</b> (одним сообщением, тоже удалится)."
    )
    await state.update_data(known_user=user, prompts=[prompt.message_id])
    await state.set_state(LoginStates.password)


@router.message(LoginStates.password, F.text)
async def login_password(
    message: Message,
    state: FSMContext,
    credentials: CredentialService,
) -> None:
    data = await state.get_data()
    user = data.get("known_user") or ""
    password = (message.text or "").strip()
    if password.startswith("/"):
        await _cancel_flow(message, state)
        return
    if not (1 <= len(password) <= 128):
        _prompt = await message.answer("❗️ Пароль 1–128 символов. Пришлите снова:")
        await _delete_message(message)
        await _track_prompt(state, _prompt.message_id)
        return

    await credentials.save(
        message.from_user.id, SlskCreds(user=user, password=password)
    )
    for message_id in data.get("prompts", []):
        await _delete_prompt(message.bot, message.chat.id, message_id)
    await _delete_message(message)
    await state.clear()
    await message.answer(
        f"✅ Soulseek-аккаунт <code>{_escape.escape(user)}</code> подключён.\n"
        "Ищите песни: просто пришлите «артист - трек»."
    )


@router.message(LoginStates.username)
@router.message(LoginStates.password)
async def login_invalid_content(message: Message, state: FSMContext) -> None:
    prompt = await message.answer("❗️ Жду текст. Если надоело — /cancel.")
    await _delete_message(message)
    await _track_prompt(state, prompt.message_id)
