"""Отбор и ранжирование кандидатов (порт StreamToOffline CandidateSelector)."""

from __future__ import annotations

from finderbot.tools.sockseek import TrackQuery
from finderbot.tools.songselect import (
    CandidateSelector,
    SelectionPolicy,
    SelectionReport,
)
from helpers import make


def test_version_filters_auto() -> None:
    selector = CandidateSelector()
    policy = SelectionPolicy()
    checks = (
        ("Album\\01 - Song.mp3", True),
        ("Album\\Song (Original Mix).mp3", True),
        ("Album\\Song (Remix).mp3", False),
        ("Album\\Song (Some Remix).mp3", False),
        ("Album\\Song (Radio Edit).mp3", False),
        ("Album\\Song (Sped Up).mp3", False),
        ("Album\\Song (Slowed Reverb).mp3", False),
        ("Album\\Song (Live at Wembley).mp3", False),
        ("Album\\Cover by Joe.mp3", False),
    )
    for location, expected in checks:
        assert selector._version_matches(make(path=location), policy) is expected, location


def test_version_policy_all_passes_everything() -> None:
    selector = CandidateSelector()
    policy = SelectionPolicy(version_policy="all")
    assert selector._version_matches(make(path="Song (Remix).mp3"), policy)
    assert selector._version_matches(make(path="Song (Extended Edit).mp3"), policy)


def test_quality_min_bitrate_skips_lossless() -> None:
    selector = CandidateSelector()
    policy = SelectionPolicy(min_bitrate_kbps=192)
    assert selector._quality_matches(make(bitrate=320), policy)
    assert not selector._quality_matches(make(bitrate=160), policy)
    # lossless освобождён от требования битрейта
    assert selector._quality_matches(
        make(path="Album\\Song.flac", bitrate=None, size=30_000_000), policy
    )
    # битрейт неизвестен, файл lossy — как «не запасся» → не проходит
    assert not selector._quality_matches(make(bitrate=None), policy)


def test_length_match_by_reference() -> None:
    selector = CandidateSelector()
    policy = SelectionPolicy(length_tolerance_seconds=5)
    spec = TrackQuery(raw="Song", reference_duration=225)
    assert selector._length_matches(make(length=228), spec, policy)
    assert not selector._length_matches(make(length=300), spec, policy)
    # у кандидата неизвестна длительность — не режем
    assert selector._length_matches(make(length=None), spec, policy)
    # без эталона — вообще не фильтруем
    assert selector._length_matches(make(length=3), TrackQuery(raw="S"), policy)


def test_size_limit() -> None:
    selector = CandidateSelector()
    policy = SelectionPolicy(max_size_bytes=50_000_000)
    assert selector._size_matches(make(size=48_000_000), policy)
    assert not selector._size_matches(make(size=60_000_000), policy)


def test_rank_prefers_mp3_320_free_fast_peer() -> None:
    selector = CandidateSelector()
    first = make(peer="a", bitrate=320, upload=5000.0)
    worse_1 = make(peer="b", bitrate=192, upload=5000.0)
    worse_2 = make(peer="c", bitrate=320, upload=100.0)
    ranked, report = selector.rank(
        [worse_1, worse_2, first], TrackQuery(raw="Song"), SelectionPolicy()
    )
    assert [r.peer for r in ranked] == ["a", "c", "b"]
    assert report.best is not None and report.best.peer == "a"


def test_rank_duration_closeness_breaks_ties() -> None:
    selector = CandidateSelector()
    close = make(peer="close", bitrate=320, length=224)
    far = make(peer="far", bitrate=320, length=390)
    spec = TrackQuery(raw="Song", reference_duration=225)
    ranked, _ = selector.rank([far, close], spec, SelectionPolicy(length_tolerance_seconds=5))
    assert ranked[0].peer == "close"
    # 390 далеко от 225 +5с → помещение отфильтровано вовсе
    ranked, report = selector.rank([far], spec, SelectionPolicy(length_tolerance_seconds=5))
    assert ranked == [] and report.rejected_by_length == 1


def test_diagnose_counts_and_summary() -> None:
    selector = CandidateSelector()
    results = [
        make(),
        make(path="Song (Radio Edit).mp3"),
        make(bitrate=64),
        make(size=60_000_000),
    ]
    policy = SelectionPolicy(min_bitrate_kbps=128, max_size_bytes=50_000_000)
    ranked, report = selector.rank(results, TrackQuery(raw="Song"), policy)
    assert len(ranked) == 1
    assert report.total == 4
    assert report.eligible == 1
    assert report.rejected_by_quality == 1
    assert report.rejected_by_version == 1
    assert report.rejected_by_size == 1
    text = report.summary()
    assert "качество ×1" in text
    assert "версии ×1" in text
    assert "размер ×1" in text


def test_report_summary_all_good() -> None:
    report = SelectionReport(total=7)
    report.eligible = 7
    assert "подходят" in report.summary()
