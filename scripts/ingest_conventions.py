"""把仓库里的规范文档（CONTRIBUTING / docs）切条款入库。

用法：
    uv run python scripts/ingest_conventions.py --repo /path/to/repo
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.conventions.store import ConventionStore, ingest_repo  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="采集项目规范条款")
    parser.add_argument("--repo", required=True, help="本地克隆仓库路径")
    parser.add_argument("--db", default=str(ROOT / "data" / "conventions.db"))
    args = parser.parse_args()

    store = ConventionStore(args.db)
    ingested = ingest_repo(args.repo, store)
    print(f"本次摄入 {ingested} 条规范条款，库中现有 {store.count()} 条")
    store.close()


if __name__ == "__main__":
    main()
