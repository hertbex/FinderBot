#!/usr/bin/env python3
"""Установка внешних инструментов бота: sockseek и (на Windows) ffmpeg/ffprobe.

  python scripts/install_tools.py              # всё, что нужно этой платформе
  python scripts/install_tools.py sockseek
  python scripts/install_tools.py ffmpeg

sockseek берётся из релизов GitHub (версия зафиксирована, SHA-256 проверяется).
ffmpeg на Windows качается из gyan.dev; на Linux/macOS инструкция по установке.
Файлы кладутся в tools/bin (этот каталог в .gitignore).
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "tools" / "bin"

SOCKSEEK_VERSION = "3.0.6"
SOCKSEEK_BASE = (
    f"https://github.com/fiso64/sockseek/releases/download/v{SOCKSEEK_VERSION}/"
)
# SHA-256 из релиза v3.0.6 (gitHub API assets[].digest)
SOCKSEEK_DOWNLOADS: dict[tuple[str, str], tuple[str, str]] = {
    ("Windows", "x64"): (
        "sockseek_3.0.6_win-x64.zip",
        "aa965bdf3bc9b04757380889e1ce96ce1d57fdf89423fb3f7ebf378e469e66c4",
    ),
    ("Linux", "x64"): (
        "sockseek_3.0.6_linux-x64.tar.gz",
        "91d7d14fa1293afe94ccb0299e0103f8477a558223f62f4027f5712e4bbf521a",
    ),
    ("Linux", "arm"): (
        "sockseek_3.0.6_linux-arm.tar.gz",
        "d45b87720b6ab006e471f79055ea3865020fae0761b3e9100731729bdff9f7ea",
    ),
    ("Darwin", "x64"): (
        "sockseek_3.0.6_osx-x64.tar.gz",
        "6211374e1fca1f0b0bb4bfc6395e493c5969416e116a976f87bac4bdb99320fd",
    ),
    ("Darwin", "arm64"): (
        "sockseek_3.0.6_osx-arm64.tar.gz",
        "b7b9602b3ea0d8724b2a4dd1370c97f2f1f7175f901e7088dad714352c4926d",
    ),
}
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _system_key() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64") and system == "Darwin":
        arch = "arm64"
    elif machine in ("arm64", "aarch64") and system == "Linux":
        # релиз sockseek: только linux-arm (32-битная сборка x64-двоек нет)
        arch = "arm"
    else:
        arch = machine
    return system, arch


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        return response.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_executable(path: Path) -> None:
    if platform.system() != "Windows":
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_sockseek() -> None:
    system, arch = _system_key()
    entry = SOCKSEEK_DOWNLOADS.get((system, arch))
    if entry is None:
        print(f"✗ нет сборки sockseek для {system}/{arch}")
        sys.exit(1)
    filename, expected_sha = entry
    url = SOCKSEEK_BASE + filename
    print(f"→ Скачиваю {url} …")
    data = _download(url)
    actual_sha = _sha256(data)
    if actual_sha != expected_sha:
        print(f"✗ SHA-256 не совпал: {actual_sha} != {expected_sha}")
        sys.exit(1)
    print(f"✓ SHA-256 ок: {actual_sha}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if system == "Windows" else ""
    target = BIN_DIR / f"sockseek{suffix}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if filename.endswith(".zip"):
            archive = tmp_path / filename
            archive.write_bytes(data)
            with zipfile.ZipFile(archive) as zf:
                candidates = [
                    info
                    for info in zf.infolist()
                    if not info.is_dir() and _is_sockseek_member(info.filename)
                ]
                if not candidates:
                    print("✗ в архиве не найден sockseek-бинарь")
                    sys.exit(1)
                chosen = max(candidates, key=lambda info: info.file_size)
                extracted = tmp_path / Path(chosen.filename).name
                extracted.write_bytes(zf.read(chosen))
        else:
            archive = tmp_path / filename
            archive.write_bytes(data)
            with tarfile.open(archive, "r:gz") as tf:
                members = [
                    member
                    for member in tf.getmembers()
                    if member.isfile() and _is_sockseek_member(member.name)
                ]
                if not members:
                    print("✗ в архиве не найден sockseek-бинарь")
                    sys.exit(1)
                chosen = max(members, key=lambda member: member.file_size)
                tf.extract(chosen, tmp_path)
                extracted = tmp_path / Path(chosen.name).name
        shutil.copy2(extracted, target)

    _make_executable(target)
    print(f"✓ sockseek установлен: {target}")


def _is_sockseek_member(name: str) -> bool:
    base = Path(name).name.lower()
    system = platform.system()
    if system == "Windows":
        return base.startswith("sockseek") and base.endswith(".exe")
    return base.startswith(("sockseek", "sockseek.bin"))


def install_ffmpeg() -> None:
    system = platform.system()
    if system != "Windows":
        print("На этой платформе ffmpeg ставится системным пакетом:")
        if system == "Linux":
            print("  Debian/Ubuntu: sudo apt-get install -y ffmpeg")
            print("  Alpine (Docker): apk add ffmpeg")
        else:
            print("  macOS: brew install ffmpeg")
        return

    print(f"→ Скачиваю {FFMPEG_URL} (~90 МБ) …")
    data = _download(FFMPEG_URL)
    print(f"✓ скачано {_sha256(data)[:16]}… ({len(data) // (1024 * 1024)} МБ)")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "ffmpeg.zip"
        archive.write_bytes(data)
        wanted = ("ffmpeg.exe", "ffprobe.exe")
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                base = Path(name).name.lower()
                if base in wanted:
                    destination = BIN_DIR / base
                    destination.write_bytes(zf.read(name))
                    print(f"✓ установлен {destination}")


def _force_utf8_console() -> None:
    """Windows-консоль часто в cp1251/cp1252 — перевожу вывод в UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    _force_utf8_console()
    what = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    system, arch = _system_key()
    print(f"Платформа: {system}/{arch}, цель: tools/bin")
    if what in ("all", "sockseek"):
        install_sockseek()
    if what in ("all", "ffmpeg"):
        install_ffmpeg()
    print("Готово.")


if __name__ == "__main__":
    main()
