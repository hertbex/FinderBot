"""Парсинг выдачи sockseek (--print-json-full)."""

from __future__ import annotations

import json

import pytest

from finderbot.tools.sockseek import SockseekError, parse_results

SAMPLE = json.dumps(
    [
        {
            "User": {"Username": "Alice", "UploadSpeed": 3123.0, "HasFreeUploadSlot": True},
            "File": {
                "Length": 240,
                "Filename": "Daft Punk\\Discovery\\01 - Get Lucky.mp3",
                "Size": 9_600_000,
                "Bitrate": 320,
                "SampleRate": 44100,
                "BitDepth": 0,
            },
        },
        {
            "User": {"Username": "Bob", "UploadSpeed": 0.0, "HasFreeUploadSlot": False},
            "File": {
                "Length": 999,
                "Filename": "Get Lucky (repeat).mp3",
                "Size": 9_600_000,
                "Bitrate": 320,
                "SampleRate": 44100,
                "BitDepth": 0,
            },
        },
        {
            "User": {"Username": "Bob", "UploadSpeed": 0.0, "HasFreeUploadSlot": False},
            "File": {"Length": -1, "Filename": "readme.txt", "Size": 100, "Bitrate": 0},
        },
        {
            "User": {"Username": "Eve", "UploadSpeed": 5.0, "HasFreeUploadSlot": True},
            "File": {
                "Length": -1,
                "Filename": "password.txt.exe",
                "Size": 12345,
                "Bitrate": 0,
            },
        },
    ]
)


def test_parse_results_filters_and_dedupes() -> None:
    results = parse_results(SAMPLE)
    # readme.txt и password.txt.exe отфильтрованы (не аудио / мусор)
    # дамп файла у Bob повторяется по (peer, path) — stays once
    peers = [r.peer for r in results]
    assert peers.count("Bob") == 1
    assert all(r.ext in {"mp3", "m4a", "flac", "wav"} for r in results)
    first = results[0]
    assert first.peer == "Alice"
    assert first.size == 9_600_000
    assert first.bitrate == 320
    assert first.length == 240
    assert first.has_free_upload_slot is True
    assert "\\" in first.path  # путь не трогаем


def test_parse_results_empty() -> None:
    assert parse_results("") == []
    assert parse_results("[]") == []


def test_parse_results_bad_json() -> None:
    with pytest.raises(SockseekError):
        parse_results("{ not json", stderr="boom")
