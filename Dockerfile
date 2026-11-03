FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg/ffprobe для yt-dlp и сжатия видео
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts

# сам бот + sockseek (linux-x64 c проверкой SHA-256)
RUN pip install --no-cache-dir . \
 && python scripts/install_tools.py sockseek

# некорневой пользователь для запуска
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/data /app/downloads /app/tools/bin \
 && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "finderbot"]
