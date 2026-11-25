"""手动触发一次真实审查（不需要 webhook）。

用法：
    uv run python scripts/trigger_review.py --repo 你的用户名/仓库名 --pr 3

做什么：调 GitHub API 取该 PR 的 head/base SHA → 建一张工单 → 打印后续步骤。
接着运行 scripts/run_worker.py，它会自动 clone 仓库、审查、把评论发到真实 PR。
"""

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.tasks.models import Ticket, TicketKind  # noqa: E402
from app.tasks.store import TicketStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="手动触发一次 PR 审查")
    parser.add_argument("--repo", required=True, help="owner/repo，如 yourname/test-repo")
    parser.add_argument("--pr", type=int, required=True, help="PR 编号")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.github_token:
        sys.exit("缺少 GITHUB_TOKEN：请先在 .env 中配置")

    resp = httpx.get(
        f"https://api.github.com/repos/{args.repo}/pulls/{args.pr}",
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=20,
    )
    if resp.status_code != 200:
        sys.exit(f"获取 PR 失败（{resp.status_code}）：{resp.text[:300]}")
    data = resp.json()

    head_sha = data["head"]["sha"]
    base_sha = data["base"]["sha"]
    title = (data.get("title") or "").strip()[:80]

    store = TicketStore()
    ticket = store.create(
        Ticket(
            kind=TicketKind.REVIEW_PR,
            repo=args.repo,
            pr_number=args.pr,
            head_sha=head_sha,
            base_sha=base_sha,
            worker="reviewer",
            title=f"PR #{args.pr} {title}",
        )
    )
    print(f"已建工单 {ticket.id}（head={head_sha[:8]} base={base_sha[:8]}）")
    print("接着运行：python scripts/run_worker.py")
    print("worker 会自动 clone 仓库、审查，并把评论发到该 PR 上。")
    store.close()


if __name__ == "__main__":
    main()
