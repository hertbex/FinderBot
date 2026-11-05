"""Конфигурация бота из .env (pydantic-settings).

Все переменные окружения читаются без префикса: BOT_TOKEN, WORKERS, ...
Списки задаются в JSON-виде, например:
  ALLOWED_HOSTS=["youtube.com","youtu.be","tiktok.com","instagram.com"]
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Домены, разрешённые для скачивания видео (поддомены разрешаются автоматически)
DEFAULT_ALLOWED_HOSTS: list[str] = [
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
]


class Settings(BaseSettings):
    """Все настройки бота. См. .env.example."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str
    admin_user_id: int | None = None

    # Soulseek-креды администратора (используются, только если админ не сделал /login)
    soulseek_user: str | None = None
    soulseek_pass: str | None = None

    # Разрешённые домены для видео (поддомены разрешаются автоматически)
    allowed_hosts: list[str] = DEFAULT_ALLOWED_HOSTS

    # Лимиты Telegram
    max_file_mb: int = 48  # запас от лимита бота (50 МБ)
    max_video_minutes: int = 120  # отказ по длительности

    # Таймауты
    search_timeout_sec: int = 120
    song_download_timeout_sec: int = 900
    video_download_timeout_sec: int = 1800

    # Очередь
    workers: int = 3
    jobs_per_user: int = 1
    queue_per_user: int = 3
    requests_per_minute: int = 4

    # Пути (относительно рабочей директории запуска)
    tools_dir: Path = Path("tools/bin")
    data_dir: Path = Path("data")
    download_dir: Path = Path("downloads")

    # yt-dlp
    ytdlp_proxy: str | None = None
    ytdlp_cookies: Path | None = None

    # --- Поиск песни (конвейер в духе StreamToOffline) ---
    slsk_formats: str = "mp3,flac,m4a,wav,ogg"   # --format у sockseek
    slsk_version_policy: str = "auto"            # auto|all|original|edits|remixes
    slsk_length_tolerance_sec: int = 5           # допуск к (M:SS) из запроса
    slsk_min_bitrate: int | None = None          # минимальный битрейт lossy

    # Шифрование per-user кредов; если не задано — создаётся data/secret.key
    encrypt_key: str | None = None

    # Не удалять скачанные файлы после отправки (отладка)
    keep_files: bool = False

    # Логи
    log_level: str = "INFO"

    @field_validator("admin_user_id", "slsk_min_bitrate", mode="before")
    @classmethod
    def _empty_int_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("slsk_version_policy", mode="before")
    @classmethod
    def _check_version_policy(cls, value: object) -> object:
        value_str = str(value or "").strip().lower() or "auto"
        if value_str not in ("auto", "all", "original", "edits", "remixes"):
            raise ValueError(
                "SLSK_VERSION_POLICY допустимы: auto|all|original|edits|remixes"
            )
        return value_str

    @field_validator("ytdlp_cookies", "ytdlp_proxy", "encrypt_key", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        """Разрешаем и JSON-список, и запятую-разделитель."""
        if isinstance(value, str):
            import json

            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def is_admin(self, telegram_id: int) -> bool:
        return self.admin_user_id is not None and telegram_id == self.admin_user_id

    def admin_creds(self) -> tuple[str, str] | None:
        if self.soulseek_user and self.soulseek_pass:
            return (self.soulseek_user, self.soulseek_pass)
        return None

    @classmethod
    def from_env_bulletproof(cls) -> Self:
        """Загрузка из .env; ошибка без подсказки даёт понятное сообщение.

        Используется в app.main, чтобы вместо traceback про pydantic
        пользователь видел пошаговое «что поправить».
        """
        try:
            return cls()
        except Exception as exc:  # noqa: BLE001 — наводим порядок в любом сбое
            raise SystemExit(
                "❌ Не удалось загрузить конфиг:\n"
                f"  {exc}\n"
                "Проверьте .env (шаблон: .env.example)."
            ) from exc
