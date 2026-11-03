@echo off
chcp 65001 >nul
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
    echo Создаю виртуальное окружение...
    py -3.12 -m venv .venv || python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -e ".[dev]"
python scripts\install_tools.py

python -m finderbot
pause
