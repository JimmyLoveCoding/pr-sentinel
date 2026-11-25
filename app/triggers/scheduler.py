"""定时 Trigger（D9 实现）。

职责：扫描 watch 类 Ticket，到期时生成一次 Assignment，交给 Worker 池执行。
两周 MVP 只支持一种调度格式：daily@HH:MM（用户本地时区）。

对应 DeepSeek Super-agent 的 Trigger/Thread 概念：
- Trigger：定时或事件（本 MVP 只做定时）
- Thread：同一主题下的多次执行（日报连续累积）
"""

from __future__ import annotations

from app.tasks.models import Ticket
from app.tasks.store import TicketStore


def list_due_watch_tickets(store: TicketStore, now_hm: str) -> list[Ticket]:
    """返回当前时刻应执行的 watch 任务。

    D9 实现：解析 schedule（如 "daily@09:00"），与 now_hm（如 "09:00"）比对，
    并防止同一分钟重复触发（用上次执行时间或幂等键去重）。
    """
    raise NotImplementedError("D9：实现 watch ticket 的到期判断与去重")
