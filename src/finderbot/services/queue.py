"""Очередь задач с воркерами и per-user лимитами."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from aiogram import Bot

from finderbot.services.progress import Progress

log = logging.getLogger(__name__)

Runner = Callable[[ "Job", "Progress"], Awaitable[None]]


class QueueFull(RuntimeError):
    """У пользователя исчерпаны слоты очереди."""


@dataclass
class Job:
    """Одна единица работы (скачивание)."""

    user_id: int
    chat_id: int
    message_id: int  # сообщение-прогрессер
    kind: str
    label: str
    payload: dict
    seq: int = 0
    started_at: float | None = None
    extra: dict = field(default_factory=dict)


class QueueManager:
    """Пул воркеров; у одного юзера 1 запущенная задача + до N в очереди."""

    def __init__(
        self,
        bot: Bot,
        runners: dict[str, Runner],
        *,
        workers: int = 3,
        queue_per_user: int = 3,
    ) -> None:
        self._bot = bot
        self._runners = runners
        self._queue: deque[Job] = deque()
        self._wake = asyncio.Event()
        self._running: dict[int, Job] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._worker_tasks: list[asyncio.Task] = []
        self._seq = itertools.count(1)
        self._workers = max(1, int(workers))
        self._queue_per_user = max(0, int(queue_per_user))

    # ---Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self._worker_tasks = [asyncio.create_task(self._worker_loop()) for _ in range(self._workers)]
        log.info("Очередь запущена: %s воркеров", self._workers)

    async def stop(self) -> None:
        for task in self._worker_tasks:
            task.cancel()
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._worker_tasks, *self._tasks.values(), return_exceptions=True)
        self._worker_tasks.clear()
        self._tasks.clear()
        self._running.clear()
        log.info("Очередь остановлена")

    # --- Приём --------------------------------------------------------------

    async def submit(
        self,
        *,
        user_id: int,
        chat_id: int,
        message_id: int,
        kind: str,
        label: str,
        payload: dict,
        extra: dict | None = None,
    ) -> Job:
        """Добавляет задачу или поднимает QueueFull."""
        queued_by_user = sum(1 for job in self._queue if job.user_id == user_id)
        running = self._running.get(user_id) is not None
        if queued_by_user >= self._queue_per_user + (0 if running else 1):
            raise QueueFull(
                f"Слот переполнен: у вас {queued_by_user} задач в очереди "
                f"и {'уже идёт' if running else 'статус активен'}"
            )
        job = Job(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            kind=kind,
            label=label,
            payload=payload,
        )
        job.seq = next(self._seq)
        if extra:
            job.extra = extra
        self._queue.append(job)
        self._wake.set()
        return job

    # --- Работа -------------------------------------------------------------

    def _try_pop(self) -> Job | None:
        for index, job in enumerate(self._queue):
            if job.user_id not in self._running:
                del self._queue[index]
                return job
        return None

    async def _worker_loop(self) -> None:
        while True:
            job = self._try_pop()
            if job is None:
                self._wake.clear()
                job = self._try_pop()  # вторая попытка: not потерять wake
                if job is None:
                    await self._wake.wait()
                    continue
            task = asyncio.create_task(self._run_job(job))
            self._tasks[job.user_id] = task
            try:
                await task
            except asyncio.CancelledError:
                log.info("Задача %s отменена (user %s)", job.seq, job.user_id)
            except Exception:  # noqa: BLE001
                log.exception("Задача %s упала", job.seq)
            finally:
                if self._tasks.get(job.user_id) is task:
                    self._tasks.pop(job.user_id, None)
                self._running.pop(job.user_id, None)
                self._wake.set()  # освободились — возможно есть её задача

    async def _run_job(self, job: Job) -> None:
        self._running[job.user_id] = job
        job.started_at = time.monotonic()
        log.info("Задача %s [%s] стартует: %s", job.seq, job.kind, job.label)
        progress = Progress(self._bot, job.chat_id, job.message_id)
        runner = self._runners.get(job.kind)
        if runner is None:
            await progress.fail(f"Задача неизвестного типа: {job.kind}")
            return
        try:
            await runner(job, progress)
        except asyncio.CancelledError:
            await progress.finish("🚫 Задача отменена")
            raise
        except Exception as exc:  # noqa: BLE001 — наружу пользователю дружелюбно
            log.exception("Сбой задачи %s", job.seq)
            text = str(exc).strip()
            await progress.fail(f"Не вышло: {text}" if text else "Не вышло: внутренняя ошибка")
        else:
            log.info("Задача %s завершена", job.seq)

    # --- Управление ---------------------------------------------------------

    async def cancel_user(self, user_id: int) -> bool:
        """Отменяет текущую и убирает из очереди задачи юзера."""
        cancelled = False
        task = self._tasks.get(user_id)
        if task is not None and not task.done():
            task.cancel()
            cancelled = True
        remaining: deque[Job] = deque()
        for job in self._queue:
            if job.user_id == user_id:
                try:
                    await self._bot.edit_message_text(
                        "🔕 Задача убрана из очереди",
                        chat_id=job.chat_id,
                        message_id=job.message_id,
                    )
                except Exception:  # noqa: BLE001
                    pass
            else:
                remaining.append(job)
        self._queue = remaining
        return cancelled

    def describe_user(self, user_id: int) -> str | None:
        """Короткий статус юзера или None, если ничего нет."""
        running = self._running.get(user_id)
        queued = [job for job in self._queue if job.user_id == user_id]
        parts: list[str] = []
        if running:
            parts.append(f"▶️ работает: {running.label}")
        for position, job in enumerate(queued, 1):
            parts.append(f"⏳ в очереди {position}: {job.label}")
        return "\n".join(parts) if parts else None

    def stats(self) -> dict[str, int | bool]:
        return {
            "workers": self._workers,
            "running": len(self._running),
            "queued": len(self._queue),
        }
