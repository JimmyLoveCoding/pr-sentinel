"""启动 Worker 池，持续处理工单。

用法：
    uv run python scripts/run_worker.py                  # 自动 clone 模式（推荐）
    uv run python scripts/run_worker.py --repo /本地路径   # 指定本地仓库（单仓库调试）

自动 clone 模式：按工单里的 owner/repo 把仓库 clone/pull 到 data/repos/，
并 checkout 到工单的 head_sha 后审查——每张工单都能审不同仓库。

前置：.env 中配置 OPENAI_API_KEY；要发真评论还需 GITHUB_TOKEN。
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.pool import start_pool  # noqa: E402
from app.bughistory.store import BugHistoryStore  # noqa: E402
from app.conventions.store import ConventionStore  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.github.client import GitHubCommentClient  # noqa: E402
from app.github.repo_cache import checkout_commit, ensure_repo  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.review.pipeline import review_ticket  # noqa: E402
from app.review.store import ReviewCommentStore  # noqa: E402
from app.tasks.store import TicketStore  # noqa: E402
from app.tools.base import ToolRegistry  # noqa: E402
from app.tools.registry import build_registry  # noqa: E402


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    ticket_store = TicketStore()

    if settings.github_token:
        comment_store = GitHubCommentClient(settings)
        print("评论将发布到真实 GitHub")
    else:
        comment_store = ReviewCommentStore()
        print("未配置 GITHUB_TOKEN，评论写入本地 mock 库")

    bug_db = ROOT / "data" / "bug_history.db"
    conv_db = ROOT / "data" / "conventions.db"
    registries: dict[Path, ToolRegistry] = {}

    def registry_for(repo_root: Path) -> ToolRegistry:
        if repo_root not in registries:
            registries[repo_root] = build_registry(
                repo_root,
                bug_store=BugHistoryStore(bug_db) if bug_db.exists() else None,
                conv_store=ConventionStore(conv_db) if conv_db.exists() else None,
            )
        return registries[repo_root]

    llm = LLMClient()

    async def handler(ticket):
        if args.repo:  # 单仓库调试模式：直接使用给定目录
            repo_root = Path(args.repo).resolve()
        else:  # 自动模式：按工单 clone/pull 并切到 head_sha
            repo_root = ensure_repo(
                ticket.repo,
                pr_number=ticket.pr_number,
                token=settings.github_token,
            )
            checkout_commit(repo_root, ticket.head_sha)
        return await review_ticket(
            ticket,
            repo_root=repo_root,
            registry=registry_for(repo_root),
            comment_store=comment_store,
            llm=llm,
        )

    stop, tasks = start_pool(ticket_store, handler, workers=args.workers)
    print(f"Worker 池已启动：{args.workers} 个工人。Ctrl+C 停止。")
    try:
        await asyncio.gather(*tasks)
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        comment_store.close()
        ticket_store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="启动审查 Worker 池")
    parser.add_argument(
        "--repo",
        default=None,
        help="本地仓库路径（单仓库调试）；省略则按工单自动 clone",
    )
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
