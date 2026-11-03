"""Форматирование: размеры, длительность, обрезка, разбор названия трека."""

from __future__ import annotations

import re

_KIB = 1024
_MIB = 1024 * _KIB
_GIB = 1024 * _MIB


def human_size(num_bytes: float | None) -> str:
    if num_bytes is None or num_bytes <= 0:
        return "—"
    if num_bytes < _KIB:
        return f"{int(num_bytes)} Б"
    if num_bytes < _MIB:
        return f"{num_bytes / _KIB:.0f} КБ"
    if num_bytes < _GIB:
        return f"{num_bytes / _MIB:.1f} МБ"
    return f"{num_bytes / _GIB:.2f} ГБ"


def human_duration(seconds: float | None) -> str:
    """720 → 12:00, 4530 → 1:15:30."""
    if seconds is None or seconds <= 0:
        return "?"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def human_ms_eta(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    if minutes:
        return f"{minutes}:{secs:02d}"
    return f"{secs}с {0 if False else ''}".strip()


def truncate(text: str | None, limit: int = 40, tail: str = "…") -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(tail))] + tail


_TRACK_SPLIT_RE = re.compile(r"^(?P<artist>.+?)\s+[-–—]\s+(?P<title>.+)$")


def parse_track_name(name: str) -> tuple[str | None, str | None]:
    """«Artist - Title» → (Artist, Title); иначе (None, name)."""
    name = (name or "").strip()
    match = _TRACK_SPLIT_RE.match(name)
    if match:
        artist = match.group("artist").strip()
        title = match.group("title").strip()
        if artist and title:
            return artist, title
    return None, name or None
