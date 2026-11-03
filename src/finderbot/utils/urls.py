"""Ссылки: извлечение и allowlist доменов."""

from __future__ import annotations

import re
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\"()]+", re.IGNORECASE)


def extract_url(text: str) -> str | None:
    """Первая ссылка в тексте или None."""
    if not text:
        return None
    match = URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?")


def host_matches(host: str, base_domains: list[str]) -> bool:
    """Хост точного совпадает или в поддомене одного из базовых доменов."""
    host = (host or "").lower().rstrip(".")
    for base in base_domains:
        base = base.lower().lstrip(".")
        if not base:
            continue
        if host == base or host.endswith("." + base):
            return True
    return False


def url_host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def is_allowed_url(url: str, allowed: list[str]) -> bool:
    return host_matches(url_host(url), allowed)
