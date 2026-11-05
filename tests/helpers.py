"""Общий фабрикатор кандидатов для тестов."""

from __future__ import annotations

from pathlib import Path

from finderbot.tools.sockseek import SlskResult


def make(
    peer: str = "alice",
    path: str = "Album\\01 - Song.mp3",
    *,
    size: int = 9_600_000,
    bitrate: int | None = 320,
    length: int | None = 240,
    upload: float = 1000.0,
    slot: bool = True,
) -> SlskResult:
    """Кандидат-заглушка (ext выводится из пути)."""
    return SlskResult(
        peer=peer,
        upload_speed=upload,
        has_free_upload_slot=slot,
        path=path,
        size=size,
        bitrate=bitrate,
        sample_rate=44100,
        bit_depth=None,
        length=length,
        ext=Path(path).suffix.lstrip(".").lower(),
    )
