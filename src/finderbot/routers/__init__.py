from __future__ import annotations

from finderbot.routers.auth import router as auth_router
from finderbot.routers.candidates import CandidateRegistry
from finderbot.routers.song import router as song_router
from finderbot.routers.start import router as start_router
from finderbot.routers.video import VideoOptionRegistry
from finderbot.routers.video import router as video_router

__all__ = [
    "CandidateRegistry",
    "VideoOptionRegistry",
    "auth_router",
    "song_router",
    "start_router",
    "video_router",
]


def all_routers() -> tuple[object, ...]:
    """Порядок важен: start → auth → video → song (последний ловит любой текст)."""
    return (start_router, auth_router, video_router, song_router)
