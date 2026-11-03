"""Планировщик видео и парсинг yt-dlp."""

from __future__ import annotations

from finderbot.tools.videoplan import audio_bitrate, budget_kbps, plan_video
from finderbot.tools.ytdlp import friendly_error, parse_info

SAMPLE_INFO = {
    "_type": "video",
    "id": "dQw4w9WgXcQ",
    "title": "Never Gonna Give You Up",
    "uploader": "Rick Astley",
    "duration": 212.5,
    "height": 1080,
    "ext": "mp4",
}


def test_parse_info_basic() -> None:
    info = parse_info(SAMPLE_INFO, "https://youtu.be/dQw4w9WgXcQ")
    assert info.video_id == "dQw4w9WgXcQ"
    assert info.duration == 212
    assert info.height == 1080
    assert info.uploader == "Rick Astley"
    assert "Rick Astley" in info.short_caption


def test_parse_info_playlist_takes_single() -> None:
    playlist = {
        "_type": "playlist",
        "entries": [SAMPLE_INFO, SAMPLE_INFO],
    }
    info = parse_info(playlist, "https://youtube.com/hm")
    assert info.video_id == "dQw4w9WgXcQ"


def test_plan_video_short_is_direct() -> None:
    plan = plan_video(None, 48)
    assert plan.kind == "direct"

    plan = plan_video(60, 48)
    assert plan.kind == "direct"
    assert plan.height == 1080


def test_plan_video_medium_720p() -> None:
    plan = plan_video(600, 48)
    assert plan.kind == "direct"
    assert plan.height == 720


def test_plan_video_long_compress() -> None:
    plan = plan_video(900, 48)
    assert plan.kind == "compress"
    assert plan.video_kbps is not None


def test_plan_video_very_long_audio() -> None:
    plan = plan_video(2700, 48)
    assert plan.kind == "audio"
    assert plan.audio_kbps and 96 <= plan.audio_kbps <= 320


def test_plan_video_huge_reject() -> None:
    plan = plan_video(14400, 48)
    assert plan.kind == "reject"


def test_budget_consistent() -> None:
    assert budget_kbps(48, 600) == int(48 * 1024 * 1024 * 8 * 0.93 / 600 / 1000)


def test_audio_bitrate_within_bounds() -> None:
    assert audio_bitrate(None) == 320
    value = audio_bitrate(3600)
    assert 96 <= value <= 320


def test_friendly_error_youtube_ban() -> None:
    message = friendly_error("ERROR: Sign in to confirm you're not a bot")
    assert "YouTube" in message or "прокси" in message


def test_friendly_error_private() -> None:
    assert "приватное" in friendly_error("ERROR: Private video. Sign in if you've been granted access")


def test_friendly_error_fallback() -> None:
    result = friendly_error("ERROR: что-то редкое случилось")
    assert "случилось" in result
