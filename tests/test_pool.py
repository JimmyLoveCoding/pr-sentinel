import asyncio

from app.agent.pool import start_pool
from app.review.pipeline import ReviewOutcome
from app.tasks.models import Ticket, TicketKind, TicketStatus
from app.tasks.store import TicketStore


def make_ticket(i: int) -> Ticket:
    return Ticket(
        kind=TicketKind.REVIEW_PR,
        repo="org/app",
        pr_number=i,
        head_sha=f"sha{i}",
        worker="reviewer",
        title=f"PR #{i}",
    )


async def wait_until(predicate, timeout: float = 5.0) -> None:
    """轮询等待条件成立；超时则断言失败。"""
    steps = int(timeout / 0.01)
    for _ in range(steps):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("等待超时")


def test_pool_processes_all_tickets(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    for i in range(1, 4):
        store.create(make_ticket(i))

    processed: list[int] = []

    async def handler(ticket: Ticket) -> ReviewOutcome:
        processed.append(ticket.pr_number)
        await asyncio.sleep(0.01)
        return ReviewOutcome(ok=True)

    async def run() -> None:
        stop, tasks = start_pool(store, handler, workers=2, poll_interval=0.01)
        await wait_until(lambda: len(store.list(TicketStatus.DONE)) == 3)
        stop.set()
        await asyncio.gather(*tasks)

    asyncio.run(run())

    assert len(store.list(TicketStatus.DONE)) == 3
    assert sorted(processed) == [1, 2, 3]  # 每张单子恰好处理一次
    store.close()


def test_failed_ticket_becomes_failed(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    store.create(make_ticket(1))

    calls: list[str] = []

    async def handler(ticket: Ticket) -> ReviewOutcome:
        calls.append(ticket.id)
        return ReviewOutcome(ok=False, error="boom")

    async def run() -> None:
        stop, tasks = start_pool(
            store, handler, workers=1, poll_interval=0.01, max_retries=0
        )
        await wait_until(lambda: bool(store.list(TicketStatus.FAILED)))
        stop.set()
        await asyncio.gather(*tasks)

    asyncio.run(run())

    failed = store.list(TicketStatus.FAILED)
    assert len(failed) == 1
    assert "boom" in failed[0].error
    assert len(calls) == 1  # max_retries=0：失败即终态
    store.close()


def test_handler_exception_does_not_kill_worker(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    store.create(make_ticket(1))

    async def handler(ticket: Ticket) -> ReviewOutcome:
        raise RuntimeError("handler 崩了")

    async def run() -> None:
        stop, tasks = start_pool(
            store, handler, workers=1, poll_interval=0.01, max_retries=0
        )
        await wait_until(lambda: bool(store.list(TicketStatus.FAILED)))
        stop.set()
        await asyncio.gather(*tasks)

    asyncio.run(run())

    failed = store.list(TicketStatus.FAILED)
    assert len(failed) == 1
    assert "handler 崩了" in failed[0].error
    store.close()


def test_idle_worker_stops_cleanly(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")

    async def handler(ticket: Ticket) -> ReviewOutcome:  # pragma: no cover
        return ReviewOutcome(ok=True)

    async def run() -> None:
        stop, tasks = start_pool(store, handler, workers=2, poll_interval=0.01)
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.gather(*tasks)  # 没有任务时也能干净退出

    asyncio.run(run())
    store.close()
