#!/usr/bin/env python3
"""Проверка окружения FinderBot. Запуск: python scripts/doctor.py"""

from __future__ import annotations

import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from finderbot.tools.paths import ToolPaths  # noqa: E402

REQUIRED_PACKAGES = ("aiogram", "pydantic_settings", "aiosqlite", "cryptography", "yt_dlp")
WIN = platform.system() == "Windows"
SUFFIX = ".exe" if WIN else ""


def check_python() -> tuple[bool, str]:
    version = sys.version_info
    ok = version >= (3, 12)
    return ok, f"Python {version.major}.{version.minor}.{version.micro}"


def check_packages() -> tuple[bool, list[str]]:
    lines: list[str] = []
    ok = True
    for package in REQUIRED_PACKAGES:
        try:
            installed = pkg_version(package)
            lines.append(f"✓ {package} {installed}")
        except PackageNotFoundError:
            ok = False
            lines.append(f"✗ {package} не найден (pip install -e .[dev])")
    return ok, lines


def check_tools() -> tuple[bool, list[str]]:
    tools = ToolPaths.resolve(REPO_ROOT / "tools" / "bin")
    lines: list[str] = []
    ok = True

    def try_run(exe: Path | None, args: list[str], name: str) -> None:
        nonlocal ok

        if exe is None:
            lines.append(f"✗ {name} отсутствует (python scripts/install_tools.py)")
            ok = False
            return
        try:
            completed = subprocess.run(
                [str(exe), *args], capture_output=True, text=True, timeout=30
            )
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()
            first = tail[0][:60] if tail else ""
            lines.append(f"✓ {name}: {first}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            lines.append(f"✗ {name} не запускается: {type(exc).__name__}")

    try_run(tools.sockseek, ["--help"], "sockseek")
    try_run(tools.ffmpeg, ["-version"], "ffmpeg")
    try_run(tools.ffprobe, ["-version"], "ffprobe")

    return ok, lines


def check_env() -> tuple[bool, list[str]]:
    lines: list[str] = []
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        lines.append("✗ .env нет — скопируйте .env.example → .env и введите BOT_TOKEN")
        return False, lines
    lines.append("✓ .env существует")
    token = ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
    if token:
        lines.append(f"✓ BOT_TOKEN задан ({token[:4]}…{len(token)} симв)")
    else:
        return False, [*lines, "✗ BOT_TOKEN пустой"]
    return True, lines


def check_dirs() -> tuple[bool, list[str]]:
    ok = True
    lines: list[str] = []
    for name in ("data", "downloads"):
        path = REPO_ROOT / name
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".doctor"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            lines.append(f"✓ {name}/ доступна на запись")
        except OSError as exc:
            ok = False
            lines.append(f"✗ {name}/ не доступна: {exc}")
    return ok, lines


def _force_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    _force_utf8_console()
    checks = [
        check_python(),
        check_packages(),
        check_tools(),
        check_env(),
        check_dirs(),
    ]
    print(f"Deep check окружения FinderBot ({platform.platform()})")
    print("=" * 60)
    all_ok = True
    for passed, lines in checks:
        for line in lines:
            print(line)
        all_ok &= passed
    print("=" * 60)
    print("✔ Окружение готово" if all_ok else "⚠️ Есть проблемы — исправьте и повторите")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
