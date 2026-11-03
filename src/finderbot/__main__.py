"""Точка входа: python -m finderbot."""

from __future__ import annotations

import asyncio

from finderbot.app import main


def main_entry() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main_entry()
