"""Ticket 持久化（SQLite DAO）。

M1 的承诺：
- 幂等创建：同一 (repo, pr, head_sha) 重复事件只保留一张工单
- 旧单作废：同 PR 有更新的 head_sha 时，旧工单批量标 SUPERSEDED（不是失败）
- 原子领取：claim_one 以 "UPDATE ... WHERE status='created'" 抢占，不会重复派发
- 状态机约束：非法转移抛 IllegalTransition
- 失败重试：mark_failed 累加 retry_count，未超上限退回 created 重新排队
- 僵尸回收：recover_stale 把长时间无更新的 assigned/running 工单按失败处理
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.tasks.models import Ticket, TicketKind, TicketStatus, can_transition

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "tickets.db"

_SCHEMA = """
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    head_sha TEXT NOT NULL,
    worker TEXT NOT NULL,
    base_sha TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
"""

_OPEN_STATUSES = (
    TicketStatus.CREATED,
    TicketStatus.ASSIGNED,
    TicketStatus.RUNNING,
    TicketStatus.WAITING_APPROVAL,
)


def _now() -> str:
    return datetime.now().isoformat()


class IllegalTransition(ValueError):
    """非法的状态转移。"""


class TicketStore:
    def __init__(self, db_path: Path | str = _DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：允许跨线程使用同一连接（Web 框架会在不同线程执行请求）。
        # 当前为单进程、请求串行，安全；M7 上并发 Worker 时改为"每 Worker 一条连接"或加锁。
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)#和数据库文件通信的渠道，提供了execute()、commit()、rollback()等方法来执行SQL语句和管理事务。
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ---------- 内部方法不对外 ----------

    def _init_schema(self) -> None:
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(tickets)")}
        if cols and "repo" not in cols:
            # 开发期迁移：M0 的旧表结构直接废弃（本地数据可弃）
            self._conn.execute("DROP TABLE tickets")
            cols = set()
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS tickets ({_SCHEMA})")
        if cols and "base_sha" not in cols:
            # M9a 增量迁移：给老表补列（SQLite 支持带默认值的 ADD COLUMN，数据不丢）
            self._conn.execute(
                "ALTER TABLE tickets ADD COLUMN base_sha TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()

    def _get_or_raise(self, ticket_id: str) -> Ticket:
        ticket = self.get(ticket_id)
        if ticket is None:
            raise KeyError(f"工单不存在: {ticket_id}")
        return ticket

    def _set_status(
        self,
        ticket_id: str,
        dst: TicketStatus,
        *,
        error: str | None = None,
        bump_retry: bool = False,
    ) -> Ticket:
        ticket = self._get_or_raise(ticket_id)
        if not can_transition(ticket.status, dst):
            raise IllegalTransition(
                f"非法状态转移 {ticket.status.value} -> {dst.value}（工单 {ticket_id}）"
            )
        retry = ticket.retry_count + (1 if bump_retry else 0)
        self._conn.execute(
            "UPDATE tickets SET status = ?, error = ?, retry_count = ?, updated_at = ?"
            " WHERE id = ?",
            (dst.value, error, retry, _now(), ticket_id),
        )
        self._conn.commit()
        return self._get_or_raise(ticket_id)

    #---------- 创建 ----------

    def create(self, ticket: Ticket) -> Ticket:
        """幂等创建。

        同一 (repo, pr_number, head_sha) 已存在时直接返回已有工单；
        否则先把同 PR 其它旧 SHA 的未完结工单标为 SUPERSEDED，再插入新工单。
        """
        existing = self._conn.execute(
            "SELECT id FROM tickets WHERE repo = ? AND pr_number = ? AND head_sha = ?",
            (ticket.repo, ticket.pr_number, ticket.head_sha),
        ).fetchone()#fetchone() 只返回第一条记录，如果有多条符合条件的记录，其他记录将被忽略。
        if existing:
            return self._get_or_raise(existing["id"])

        self.supersede_stale(ticket.repo, ticket.pr_number, keep_sha=ticket.head_sha)
        self._conn.execute(
            "INSERT INTO tickets (id, kind, repo, pr_number, head_sha, worker, base_sha,"
            " title, status, retry_count, error, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ticket.id,
                ticket.kind.value,
                ticket.repo,
                ticket.pr_number,
                ticket.head_sha,
                ticket.worker,
                ticket.base_sha,
                ticket.title,
                ticket.status.value,
                ticket.retry_count,
                ticket.error,
                ticket.created_at.isoformat(),
                ticket.updated_at.isoformat(),
            ),
        )
        self._conn.commit()
        return ticket

    # ---------- 查询 ----------

    def get(self, ticket_id: str) -> Ticket | None:
        row = self._conn.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        return self._row_to_ticket(row) if row else None

    def list(self, status: TicketStatus | None = None) -> list[Ticket]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM tickets ORDER BY created_at"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY created_at",
                (status.value,),
            ).fetchall()
        return [self._row_to_ticket(row) for row in rows]

    # ---------- 状态流转 ----------

    def claim_one(self) -> Ticket | None:
        """原子领取：找到最早排队的一张，抢占为 ASSIGNED。"""
        row = self._conn.execute(
            "SELECT id FROM tickets WHERE status = ? ORDER BY created_at LIMIT 1",
            (TicketStatus.CREATED.value,),
        ).fetchone()
        if row is None:
            return None

        updated = self._conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (TicketStatus.ASSIGNED.value, _now(), row["id"], TicketStatus.CREATED.value),
        )
        self._conn.commit()
        if updated.rowcount != 1:
            return None  # 被并发领取者抢先，本轮放弃
        return self._get_or_raise(row["id"])

    def start(self, ticket_id: str) -> Ticket:
        """领取确认后开始执行：assigned -> running。"""
        return self._set_status(ticket_id, TicketStatus.RUNNING)

    def update_status(self, ticket_id: str, dst: TicketStatus) -> Ticket:
        return self._set_status(ticket_id, dst)

    def mark_failed(self, ticket_id: str, error: str, max_retries: int = 2) -> Ticket:
        """失败处理：重试未超上限 → 退回 CREATED 重新排队；超限 → FAILED。"""
        ticket = self._get_or_raise(ticket_id)
        if ticket.retry_count < max_retries:
            return self._set_status(
                ticket_id, TicketStatus.CREATED, error=error, bump_retry=True
            )
        return self._set_status(
            ticket_id, TicketStatus.FAILED, error=error, bump_retry=True
        )

    def supersede_stale(self, repo: str, pr_number: int, keep_sha: str) -> int:
        """同 PR 旧 SHA 的未完结工单批量作废，返回作废数量。"""
        placeholders = ",".join("?" * len(_OPEN_STATUSES))
        cur = self._conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ?"
            " WHERE repo = ? AND pr_number = ? AND head_sha != ?"
            f" AND status IN ({placeholders})",
            (
                TicketStatus.SUPERSEDED.value,
                _now(),
                repo,
                pr_number,
                keep_sha,
                *[s.value for s in _OPEN_STATUSES],
            ),
        )
        self._conn.commit()
        return cur.rowcount

    def recover_stale(self, max_age_minutes: int = 10, max_retries: int = 2) -> int:
        """僵尸回收：长时间无更新的 assigned/running 工单按失败处理。"""
        cutoff = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat()
        rows = self._conn.execute(
            "SELECT id FROM tickets WHERE status IN (?, ?) AND updated_at < ?",
            (TicketStatus.ASSIGNED.value, TicketStatus.RUNNING.value, cutoff),
        ).fetchall()
        for row in rows:
            self.mark_failed(
                row["id"], error="stale: Worker 超时未更新", max_retries=max_retries
            )
        return len(rows)

    # ---------- 行映射 ----------

    @staticmethod#通过数据库中的行数据创建一个 Ticket 对象
    def _row_to_ticket(row: sqlite3.Row) -> Ticket:
        return Ticket(
            id=row["id"],
            kind=TicketKind(row["kind"]),
            repo=row["repo"],
            pr_number=row["pr_number"],
            head_sha=row["head_sha"],
            worker=row["worker"],
            base_sha=row["base_sha"],
            title=row["title"],
            status=TicketStatus(row["status"]),
            retry_count=row["retry_count"],
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def close(self) -> None:
        self._conn.close()#关闭通道的方法，释放资源，确保数据完整性和一致性。
