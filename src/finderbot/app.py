"""Сборка приложения: сервисы, роутеры, очередь, запуск polling."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from finderbot.config import Settings
from finderbot.middleware import PrivateOnlyMiddleware, RateLimitMiddleware
from finderbot.routers import all_routers
from finderbot.routers.candidates import CandidateRegistry, VideoOptionRegistry
from finderbot.routers.song import make_song_runner
from finderbot.routers.video import UrlFileCache, make_video_runner
from finderbot.services.queue import QueueManager
from finderbot.services.sender import Sender
from finderbot.storage.creds import CredentialService
from finderbot.storage.crypto import Vault, ensure_fernet
from finderbot.storage.db import Store
from finderbot.tools.paths import ToolPaths
from finderbot.tools.sockseek import SockseekClient
from finderbot.tools.ytdlp import YtDlp

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    )
    # шумные логи aiogram — только предупреждения
    logging.getLogger("aiogram.client.session").setLevel(logging.WARNING)


async def main() -> None:
    settings = Settings.from_env_bulletproof()
    setup_logging(settings.log_level)

    Path(settings.download_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    tools = ToolPaths.resolve(settings.tools_dir)
    for line in tools.missing_report():
        logger.warning("⚠️ %s", line)

    store = Store(settings.data_dir / "finderbot.db")
    await store.connect()
    vault = Vault(ensure_fernet(settings))
    credentials = CredentialService(store, vault, settings)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    sender = Sender(
        bot,
        store,
        downloads_root=Path(settings.download_dir),
        keep_files=settings.keep_files,
    )

    sockseek = SockseekClient(
        executable=tools.sockseek or Path("sockseek-НЕ_УСТАНОВЛЕН"),
        search_timeout=settings.search_timeout_sec,
        download_timeout=settings.song_download_timeout_sec,
    )
    ytdlp = YtDlp(
        proxy=settings.ytdlp_proxy,
        cookies=settings.ytdlp_cookies,
        ffmpeg_dir=tools.ffmpeg.parent if tools.ffmpeg else None,
        timeout=settings.video_download_timeout_sec,
    )

    candidates = CandidateRegistry()
    videos = VideoOptionRegistry()
    url_cache = UrlFileCache()

    run_video, run_video_audio = make_video_runner(
        bot=bot,
        ytdlp=ytdlp,
        sender=sender,
        settings=settings,
        tools=tools,
        videos=videos,
        url_cache=url_cache,
    )
    run_song = make_song_runner(
        sockseek=sockseek,
        sender=sender,
        settings=settings,
        tools=tools,
        credentials=credentials,
    )

    queue = QueueManager(
        bot,
        {"song": run_song, "video": run_video, "video_audio": run_video_audio},
        workers=settings.workers,
        queue_per_user=settings.queue_per_user,
    )

    dp = Dispatcher()
    dp.update.outer_middleware(PrivateOnlyMiddleware())
    dp.update.outer_middleware(
        RateLimitMiddleware(settings.requests_per_minute, settings.admin_user_id)
    )
    for built_router in all_routers():
        dp.include_router(built_router)

    queue.start()
    logger.info("Бот стартует…")
    try:
        await dp.start_polling(
            bot,
            settings=settings,
            store=store,
            credentials=credentials,
            sender=sender,
            queue=queue,
            sockseek=sockseek,
            ytdlp=ytdlp,
            candidates=candidates,
            videos=videos,
            url_cache=url_cache,
        )
    finally:
        await queue.stop()
        await store.close()
        logger.info("Бот остановлен")
