"""跑评测：加载用例 → 逐条执行 → 输出指标报告。

用法：
    uv run python scripts/run_eval.py --dataset evals/datasets/review_v1.jsonl \
        --repo /path/to/cloned/repo

前置：.env 配置 OPENAI_API_KEY；用例里的 commit 必须真实存在于该仓库。
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bughistory.store import BugHistoryStore  # noqa: E402
from app.conventions.store import ConventionStore  # noqa: E402
from app.evaluation.cases import load_cases  # noqa: E402
from app.evaluation.runner import evaluate  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.tools.registry import build_registry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="pr-sentinel 评测 runner")
    parser.add_argument("--dataset", default=str(ROOT / "evals/datasets/review_v1.jsonl"))
    parser.add_argument("--repo", required=True, help="本地克隆仓库路径（含用例中的 commit）")
    parser.add_argument("--out", default=str(ROOT / "evals/reports"))
    parser.add_argument("--no-cache", action="store_true", help="忽略缓存，全部重跑")
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    print(f"载入 {len(cases)} 条用例")

    bug_db = ROOT / "data" / "bug_history.db"
    conv_db = ROOT / "data" / "conventions.db"
    registry = build_registry(
        Path(args.repo),
        bug_store=BugHistoryStore(bug_db) if bug_db.exists() else None,
        conv_store=ConventionStore(conv_db) if conv_db.exists() else None,
    )
    report = asyncio.run(
        evaluate(
            cases,
            repo_root=Path(args.repo).resolve(),
            registry=registry,
            llm=LLMClient(),
            out_dir=Path(args.out),
            use_cache=not args.no_cache,
        )
    )

    m = report["metrics"]
    print("\n===== 评测结果 =====")
    print(f"文件级检出率：{m['file_hit_rate']:.2%}")
    print(f"行级命中率：  {m['line_hit_rate']:.2%}")
    print(f"精确率（代理）：{m['precision_proxy']:.2%}")
    print(f"误报率：      {m['false_positive_rate']:.2%}")
    print(f"p95 延迟：    {m['p95_latency_s']} s")
    print(f"总 token：    {m['total_tokens']}")
    print(f"报告已写入：{args.out}")


if __name__ == "__main__":
    main()
