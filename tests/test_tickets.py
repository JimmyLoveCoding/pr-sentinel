import sqlite3
from datetime import datetime, timedelta

import pytest

from app.tasks.models import Ticket, TicketKind, TicketStatus, can_transition
from app.tasks.store import IllegalTransition, TicketStore


def make_ticket(
    head_sha: str = "aaa111", pr_number: int = 128, repo: str = "org/app"
) -> Ticket:
    return Ticket(
        kind=TicketKind.REVIEW_PR,
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        worker="reviewer",
        title=f"PR #{pr_number}",
    )


def test_create_and_get(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    ticket = store.create(make_ticket())

    got = store.get(ticket.id)
    assert got is not None
    assert got.repo == "org/app"
    assert got.pr_number == 128
    assert got.status is TicketStatus.CREATED
    store.close()


def test_create_idempotent_by_sha(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    first = store.create(make_ticket("aaa111"))
    second = store.create(make_ticket("aaa111"))  # 同一 SHA 的重复事件

    assert first.id == second.id
    assert len(store.list()) == 1
    store.close()


def test_new_sha_supersedes_old(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    old = store.create(make_ticket("aaa111"))
    new = store.create(make_ticket("bbb222"))  # 同一 PR 的新提交

    assert store.get(old.id).status is TicketStatus.SUPERSEDED
    assert store.get(new.id).status is TicketStatus.CREATED
    store.close()


def test_claim_atomic_and_transitions(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    store.create(make_ticket())

    claimed = store.claim_one()
    assert claimed is not None
    assert claimed.status is TicketStatus.ASSIGNED
    assert store.claim_one() is None  # 没有第二张可领

    running = store.start(claimed.id)
    assert running.status is TicketStatus.RUNNING

    with pytest.raises(IllegalTransition):
        store.update_status(claimed.id, TicketStatus.ASSIGNED)  # running -> assigned 非法
    store.close()


def test_fail_requeues_then_fails(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    store.create(make_ticket())
    ticket = store.claim_one()
    store.start(ticket.id)

    retried = store.mark_failed(ticket.id, "LLM 超时", max_retries=1)
    assert retried.status is TicketStatus.CREATED
    assert retried.retry_count == 1  # 回到队列，等待重新领取

    store.claim_one()
    store.start(ticket.id)
    failed = store.mark_failed(ticket.id, "LLM 超时", max_retries=1)
    assert failed.status is TicketStatus.FAILED
    assert failed.retry_count == 2  # 重试耗尽，终态
    store.close()


def test_recover_stale(tmp_path) -> None:
    store = TicketStore(tmp_path / "tickets.db")
    ticket = store.create(make_ticket())
    store.claim_one()
    store.start(ticket.id)

    stale_time = (datetime.now() - timedelta(minutes=30)).isoformat()
    store._conn.execute(
        "UPDATE tickets SET updated_at = ? WHERE id = ?", (stale_time, ticket.id)
    )
    store._conn.commit()

    assert store.recover_stale(max_age_minutes=10) == 1
    assert store.get(ticket.id).status is TicketStatus.CREATED
    store.close()


def test_schema_migration_adds_base_sha(tmp_path) -> None:
    """旧版表（无 base_sha 列）应被自动补列，已有数据不丢。"""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE tickets (id TEXT PRIMARY KEY, kind TEXT NOT NULL,"
        " repo TEXT NOT NULL, pr_number INTEGER NOT NULL, head_sha TEXT NOT NULL,"
        " worker TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',"
        " status TEXT NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0,"
        " error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    store = TicketStore(db)  # 应自动执行 ALTER TABLE
    ticket = store.create(make_ticket())

    assert store.get(ticket.id).base_sha == ""
    store.close()


def test_state_machine_pure() -> None:
    assert can_transition(TicketStatus.CREATED, TicketStatus.ASSIGNED)
    assert can_transition(TicketStatus.RUNNING, TicketStatus.CREATED)
    assert not can_transition(TicketStatus.DONE, TicketStatus.RUNNING)
    assert not can_transition(TicketStatus.FAILED, TicketStatus.CREATED)
