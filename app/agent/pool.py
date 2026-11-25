"""Worker 池：领工单 → 交给 handler 处理 → 成功关单 / 失败重试。

一个 Worker 就是一个循环体；多个 Worker 并发 = 多个 create_task 跑同一个循环。
领取靠 TicketStore.claim_one 的原子抢占，两个 Worker 不可能领到同一张。

已知限制（MVP）：失败重试的工单会回到 CREATED 且 created_at 不变，
会被同一批 Worker 立刻再次领到——重试行为正确，只是没有退避等待。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.review.pipeline import ReviewOutcome
from app.tasks.models import Ticket, TicketStatus
from app.tasks.store import TicketStore

Handler = Callable[[Ticket], Awaitable[ReviewOutcome]]


async def worker_loop(
    store: TicketStore,
    handler: Handler,
    *,
    stop_event: asyncio.Event,
    poll_interval: float = 0.5,
    max_retries: int = 2,
) -> None:
    """工人循环：领单 → 标记执行中 → 执行 handler → 关单或按策略重试。"""
    while not stop_event.is_set():
        ticket = store.claim_one()
        if ticket is None:
            # 没活干：等 poll_interval，或者等到被叫停（两者谁先到算谁）
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
            continue

        store.start(ticket.id)  # assigned -> running
        try:
            outcome = await handler(ticket)
        except Exception as exc:  # handler 不该抛异常，但兜底保证 Worker 不死
            outcome = ReviewOutcome(ok=False, error=f"{type(exc).__name__}: {exc}")

        if outcome.ok:
            store.update_status(ticket.id, TicketStatus.DONE)
        else:
            store.mark_failed(
                ticket.id, outcome.error or "审查失败", max_retries=max_retries
            )


def start_pool(
    store: TicketStore,
    handler: Handler,
    *,
    workers: int = 2,
    poll_interval: float = 0.5,
    max_retries: int = 2,
) -> tuple[asyncio.Event, list[asyncio.Task]]:
    """启动 N 个 Worker，返回 (停止开关, 任务列表)。"""
    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(
            worker_loop(
                store,
                handler,
                stop_event=stop_event,
                poll_interval=poll_interval,
                max_retries=max_retries,
            )
        )
        for _ in range(workers)
    ]
    return stop_event, tasks
