"""Разбор запроса и многофазный поиск (STO-конвейер в sockseek)."""

from __future__ import annotations

from pathlib import Path

from finderbot.storage.creds import SlskCreds
from finderbot.tools.sockseek import (
    SearchFlags,
    SockseekClient,
    merge_phases,
    parse_query,
)
from helpers import make


def test_parse_query_strips_reference_duration() -> None:
    spec = parse_query("Daft Punk - Get Lucky (3:45)")
    assert spec.artist == "Daft Punk"
    assert spec.title == "Get Lucky"
    assert spec.reference_duration == 225
    assert "(3:45)" not in spec.raw


def test_parse_query_without_duration() -> None:
    spec = parse_query("Radiohead - Creep")
    assert spec.artist == "Radiohead"
    assert spec.title == "Creep"
    assert spec.reference_duration is None


def test_parse_query_no_dash() -> None:
    spec = parse_query("Creep")
    assert spec.artist is None
    assert spec.title == "Creep" or spec.raw == "Creep"
    assert spec.reference_duration is None


def test_merge_phases_dedupes_by_key() -> None:
    merged: dict[tuple[str, str, str, int], object] = {}
    first = make(peer="alice", size=100)
    duplicate = make(peer="ALICE", size=100)  # регистр пира/пути не важен
    other = make(peer="bob", size=200)
    merge_phases(merged, [first])
    merge_phases(merged, [duplicate, other])
    assert len(merged) == 2
    stored = {value.peer.lower() for value in merged.values()}
    assert stored == {"alice", "bob"}


async def test_search_exact_phase_short_circuit(monkeypatch) -> None:
    client = SockseekClient(Path("sockseek.exe"))
    queries: list[tuple[str, list[str]]] = []

    async def fake_once(self, creds, query, *, extra):  # noqa: ANN001
        queries.append((query, list(extra)))
        if query.startswith("artist=Daft Punk"):
            return [make(peer="exact")]
        return []

    monkeypatch.setattr(SockseekClient, "_search_once", fake_once)
    results, spec = await client.search(
        SlskCreds(user="u", password="p"),
        "Daft Punk - Get Lucky (3:45)",
        flags=SearchFlags(
            formats="mp3,flac", min_bitrate_kbps=192, length_tolerance_seconds=5
        ),
    )
    assert spec.reference_duration == 225
    # точная фаза вернула результат → каскад не запускался
    assert len(queries) == 1
    assert queries[0][0] == "artist=Daft Punk, title=Get Lucky"
    extra = queries[0][1]
    assert "--length-tol" in extra and extra[extra.index("--length-tol") + 1] == "5"
    assert "--format" in extra
    assert [r.peer for r in results] == ["exact"]


async def test_search_falls_back_when_exact_empty(monkeypatch) -> None:
    client = SockseekClient(Path("sockseek.exe"))
    queries: list[str] = []

    async def fake_once(self, creds, query, *, extra):  # noqa: ANN001
        queries.append(query)
        if query.startswith("title="):
            return [make(peer="from-title")]
        return []

    monkeypatch.setattr(SockseekClient, "_search_once", fake_once)
    results, _ = await client.search(
        SlskCreds(user="u", password="p"),
        "Daft Punk - Get Lucky",
    )
    # фаза 0 пуста → берём title=; artist= не потребовался
    assert queries == ["artist=Daft Punk, title=Get Lucky", "title=Get Lucky"]
    assert [r.peer for r in results] == ["from-title"]


async def test_search_cascade_for_unrecognized_text(monkeypatch) -> None:
    client = SockseekClient(Path("sockseek.exe"))
    queries: list[str] = []

    async def fake_once(self, creds, query, *, extra):  # noqa: ANN001
        queries.append(query)
        if query == "raw-text":
            return [make(peer="raw"), make(peer="raw2")]
        return []

    monkeypatch.setattr(SockseekClient, "_search_once", fake_once)
    results, spec = await client.search(
        SlskCreds(user="u", password="p"),
        "raw-text",
    )
    assert queries == ["artist=raw-text", "title=raw-text", "raw-text"]
    assert spec.artist is None
    assert {r.peer for r in results} == {"raw", "raw2"}
