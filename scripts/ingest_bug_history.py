"""把仓库历史里的 bug 修复提交采集进本地库。

用法：
    uv run python scripts/ingest_bug_history.py --repo /path/to/cloned/repo
    uv run python scripts/ingest_bug_history.py --repo . --max-commits 1000
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bughistory.store import BugHistoryStore, ingest_repo  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="采集历史 bug 修复提交")
    parser.add_argument("--repo", required=True, help="本地克隆仓库路径")
    parser.add_argument("--db", default=str(ROOT / "data" / "bug_history.db"))
    parser.add_argument("--max-commits", type=int, default=500)
    args = parser.parse_args()

    store = BugHistoryStore(args.db)
    ingested = ingest_repo(args.repo, store, max_commits=args.max_commits)
    print(f"本次采集 {ingested} 条，库中现有 {store.count()} 条")
    store.close()


if __name__ == "__main__":
    main()
