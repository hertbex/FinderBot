#!/usr/bin/env bash
# Запуск бота на Linux/macOS (venv + установка инструментов + python -m finderbot)
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "Создаю виртуальное окружение..."
    python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -e ".[dev]"
python scripts/install_tools.py || true

exec python -m finderbot
