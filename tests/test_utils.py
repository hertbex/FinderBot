"""Тесты утилит: ссылки, форматирование."""

from __future__ import annotations

from finderbot.utils.formatting import human_duration, human_size, parse_track_name, truncate
from finderbot.utils.urls import extract_url, host_matches, is_allowed_url


def test_extract_url_first_match() -> None:
    text = "смотри https://youtu.be/abc123, круто?"
    assert extract_url(text) == "https://youtu.be/abc123"


def test_extract_url_none() -> None:
    assert extract_url("просто текст") is None
    assert extract_url("") is None


def test_host_matches_suffix() -> None:
    assert host_matches("www.youtube.com", ["youtube.com"])
    assert host_matches("youtube.com", ["youtube.com"])
    assert host_matches("notyoutube.com", ["youtube.com"]) is False
    assert host_matches("vm.tiktok.com", ["tiktok.com"])


def test_is_allowed_url() -> None:
    allowed = ["youtube.com", "youtu.be", "tiktok.com", "instagram.com"]
    assert is_allowed_url("https://youtu.be/x?t=3", allowed)
    assert is_allowed_url("https://www.instagram.com/reel/abc/", allowed)
    assert is_allowed_url("https://pornhub.com/lol", allowed) is False


def test_human_size() -> None:
    assert human_size(0) == "—"
    assert human_size(None) == "—"
    assert human_size(512) == "512 Б"
    assert human_size(1536) == "2 КБ"
    value = human_size(9_600_000)
    assert value.endswith("МБ")
    assert human_size(5 * 1024 * 1024 * 1024).endswith("ГБ")


def test_human_duration() -> None:
    assert human_duration(None) == "?"
    assert human_duration(61) == "1:01"
    assert human_duration(3600) == "1:00:00"
    assert human_duration(4530) == "1:15:30"


def test_parse_track_name() -> None:
    assert parse_track_name("Daft Punk - Get Lucky") == ("Daft Punk", "Get Lucky")
    assert parse_track_name("Get Lucky") == (None, "Get Lucky")
    assert parse_track_name("AC/DC - Hells Bells") == ("AC/DC", "Hells Bells")


def test_truncate() -> None:
    assert truncate("short", limit=10) == "short"
    assert len(truncate("x" * 100, limit=10)) == 10
    assert truncate("", limit=10) == ""
