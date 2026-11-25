"""PR 事件解析：从 GitHub 风格的 JSON 里抽取路由决策。

GitHub webhook 的 payload 大致长这样（省略无关字段）：

    {
      "action": "opened",
      "pull_request": {
        "number": 128,
        "head": {"sha": "abc123..."}
      },
      "repository": {"full_name": "org/app"}
    }

只关心三件事：action 白名单、PR 号、head SHA。
"""

from dataclasses import dataclass
from typing import Literal

TaskKind = Literal["review_pr"]

HANDLED_ACTIONS = frozenset({"opened", "synchronize", "reopened"})


@dataclass
class RoutingDecision:
    task_kind: TaskKind
    worker: str
    repo: str
    pr_number: int
    head_sha: str
    base_sha: str = ""  # PR 的目标分支基准（真事件有；mock 事件为空）


def should_handle(action: str) -> bool:
    """PR 事件的 action 是否在审查白名单内。"""
    return action in HANDLED_ACTIONS


def parse_pr_event(payload: dict) -> RoutingDecision | None:
    """解析 PR 事件；白名单外的 action 返回 None。

    缺字段会抛 KeyError，由调用方（webhook 接口）转成 400 响应。
    base.sha 缺失时回退空串（兼容本地 mock 事件）。
    """
    action = payload.get("action", "")
    if not should_handle(action):
        return None

    pr = payload["pull_request"]
    return RoutingDecision(
        task_kind="review_pr",
        worker="reviewer",
        repo=payload["repository"]["full_name"],
        pr_number=pr["number"],
        head_sha=pr["head"]["sha"],
        base_sha=(pr.get("base") or {}).get("sha", ""),
    )
