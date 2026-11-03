"""Очередь задач: лимиты, выполнение, отмена."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from finderbot.services.queue import Job, QueueFull, QueueManager


class StubBot:
    async def edit_message_text(self, *args: Any, **kwargs: Any) -> None:
        return None


def make_job_payload() -> dict[str, Any]:
    return {}


async def test_submit_runs_all_with_free_workers() -> None:
    ran: list[int] = []

    async def runner(job: Job, progress) -> None:  # noqa: ANN001
        await asyncio.sleep(0.05)
        ran.append(job.user_id)

    queue = QueueManager(StubBot(), {"x": runner}, workers=3, queue_per_user=5)
    queue.start()
    await queue.submit(
        user_id=1,
        chat_id=10,
        message_id=100,
        kind="x",
        label="a",
        payload={},
    )
    await queue.submit(
        user_id=2,
        chat_id=20,
        message_id=200,
        kind="x",
        label="b",
        payload={},
    )
    for _ in range(100):
        if len(ran) == 2:
            break
        await asyncio.sleep(0.05)
    assert sorted(ran) == [1, 2]
    await queue.stop()


async def test_queue_full_when_cap_reached() -> None:
    ran: list[int] = []

    async def runner(job: Job, progress) -> None:  # noqa: ANN001
        ran.append(job.user_id)
        await asyncio.sleep(0.5)

    queue = QueueManager(StubBot(), {"x": runner}, workers=1, queue_per_user=1)
    queue.start()
    await queue.submit(user_id=1, chat_id=1, message_id=1, kind="x", label="первая", payload={})
    # вторая ещё помещается (в очереди пусто)
    await queue.submit(user_id=1, chat_id=1, message_id=1, kind="x", label="вторая", payload={})
    with pytest.raises(QueueFull):
        await queue.submit(user_id=1, chat_id=1, message_id=1, kind="x", label="третья", payload={})
    await queue.stop()


async def test_cancel_running_job() -> None:
    ran_state: dict[str, bool] = {"done": False}
    started = asyncio.Event()

    async def runner(job: Job, progress) -> None:  # noqa: ANN001
        started.set()
        await asyncio.sleep(10)
        ran_state["done"] = True

    queue = QueueManager(StubBot(), {"x": runner}, workers=1, queue_per_user=3)
    queue.start()
    await queue.submit(user_id=1, chat_id=1, message_id=1, kind="x", label="long", payload={})
    await asyncio.wait_for(started.wait(), timeout=2)
    assert await queue.cancel_user(1) is True
    for _ in range(50):
        task = queue._tasks.get(1)
        if task is None or task.done():
            break
        await asyncio.sleep(0.05)
    assert ran_state["done"] is False
    assert queue.describe_user(1) is None
    await queue.stop()
    assert ran_state["done"] is False
