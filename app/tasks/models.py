"""工单领域模型：一张审查工单的定义、状态词汇与状态机规则。

状态机（唯一权威定义在 ALLOWED_TRANSITIONS）：
    created ──claim_one──▶ assigned ──start──▶ running ──▶ done
       │                      │                  │
       │                      │                  ├─mark_failed(未超上限)──▶ created（重新排队）
       │                      │                  └─mark_failed(超上限)────▶ failed
       └──────────────────────┴──────────────────▶ superseded（同 PR 有更新 head_sha，作废）
    waiting_approval：blocker 评论待人工确认（M6 起使用）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TicketStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class TicketKind(str, Enum):
    REVIEW_PR = "review_pr"


# 合法状态转移表：状态机唯一权威定义，store 与测试都引用它
ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.CREATED: frozenset({TicketStatus.ASSIGNED, TicketStatus.SUPERSEDED}),
    TicketStatus.ASSIGNED: frozenset(
        {TicketStatus.RUNNING, TicketStatus.CREATED, TicketStatus.SUPERSEDED}
    ),
    TicketStatus.RUNNING: frozenset(
        {
            TicketStatus.DONE,
            TicketStatus.FAILED,
            TicketStatus.WAITING_APPROVAL,
            TicketStatus.CREATED,  # 失败重试：重新排队
            TicketStatus.SUPERSEDED,
        }
    ),
    TicketStatus.WAITING_APPROVAL: frozenset(
        {TicketStatus.RUNNING, TicketStatus.DONE, TicketStatus.FAILED, TicketStatus.SUPERSEDED}
    ),
    TicketStatus.DONE: frozenset(),  # 终态
    TicketStatus.FAILED: frozenset(),  # 终态
    TicketStatus.SUPERSEDED: frozenset(),  # 终态
}


def can_transition(src: TicketStatus, dst: TicketStatus) -> bool:
    """src -> dst 是否为合法转移。纯函数，无副作用。"""
    return dst in ALLOWED_TRANSITIONS[src]


@dataclass
class Ticket:
    # 必填：审哪个仓库、哪个 PR、哪个提交版本
    kind: TicketKind
    repo: str  # "owner/repo"
    pr_number: int
    head_sha: str
    worker: str  # 岗位名，对应 WORKER_SPECS 的键
    base_sha: str = ""  # PR 目标分支基准（真 GitHub 事件提供；空则管线回退 head~1）
    title: str = ""  # 人类可读标题，如 "PR #128 fix: retry logic"
    status: TicketStatus = TicketStatus.CREATED
    retry_count: int = 0
    error: str | None = None  # 最近一次失败原因
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=lambda: datetime.now())
    updated_at: datetime = field(default_factory=lambda: datetime.now())
