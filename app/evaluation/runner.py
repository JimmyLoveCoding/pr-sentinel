"""评测 runner：逐条跑用例 → 收集结果 → 聚合指标 → 写报告。

判卷规则：
- 普通用例（correctness / security / maintainability）：
  有评论命中 expected_files 即"检出"；行号在 ±5 内算"行级命中"；
  评论的文件在预期内（且有行号期望时行号也对）算"命中评论"。
- clean 用例：任何一条评论都算误报（期望零评论）。

指标口径：
- file_hit_rate：普通用例的检出率（按用例计）；
- line_hit_rate：行级命中率（按用例计，仅统计有检出机会的普通用例）；
- precision_proxy：命中评论 / 总评论（自动代理值；真实精确率需人工抽检）；
- false_positive_rate：clean 用例中出现评论的比例；
- p95_latency_s / avg_tokens：延迟与成本。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.agent.loop import ChatModel
from app.evaluation.cases import EvalCase
from app.review.pipeline import review_ticket
from app.review.store import ReviewCommentStore
from app.tasks.models import Ticket, TicketKind
from app.tools.base import ToolRegistry

LINE_TOLERANCE = 5  # 行级命中允许 ±5 行


@dataclass
class CaseResult:
    case_id: str
    layer: str
    hit: bool = False  # 检出（clean 用例：为 True 表示没误报）
    line_hit: bool = False
    posted: int = 0
    matched: int = 0  # 命中评论数
    latency_s: float = 0.0
    tokens: int = 0
    error: str = ""


def _ticket_for(case: EvalCase) -> Ticket:
    return Ticket(
        kind=TicketKind.REVIEW_PR,
        repo=case.repo,
        pr_number=case.pr_number or 1,
        head_sha=case.bug_commit,
        worker="reviewer",
        title=case.description or case.id,
    )


def _judge(case: EvalCase, comments: list[dict]) -> tuple[bool, bool, int]:
    """判卷：返回 (检出, 行级命中, 命中评论数)。

    只统计行内评论（带 file_path 的）；汇总报告评论不参与判卷。
    """
    inline_comments = [c for c in comments if c.get("file_path")]

    if case.layer == "clean":
        return len(inline_comments) == 0, True, 0

    expected = set(case.expected_files)
    hit = False
    line_hit = False
    matched = 0
    for comment in inline_comments:
        file_path = comment.get("file_path")
        if file_path not in expected:
            continue
        hit = True
        lines = case.expected_lines.get(file_path) or []
        if not lines:
            matched += 1  # 没有行号期望：文件对就算命中
            continue
        if any(abs((comment.get("line") or 0) - ln) <= LINE_TOLERANCE for ln in lines):
            line_hit = True
            matched += 1
    return hit, line_hit, matched


async def run_case(
    case: EvalCase,
    *,
    repo_root: Path,
    registry: ToolRegistry,
    llm: ChatModel,
    comments_dir: Path,
) -> tuple[CaseResult, list[dict]]:
    """跑一条用例：独立评论库 → 管线 → 判卷。"""
    store = ReviewCommentStore(comments_dir / f"{case.id}.db")
    ticket = _ticket_for(case)
    start = time.perf_counter()
    try:
        outcome = await review_ticket(
            ticket,
            repo_root=repo_root,
            registry=registry,
            comment_store=store,
            llm=llm,
            base_ref=f"{case.bug_commit}~1",
        )
        comments = store.list_for(ticket.repo, ticket.pr_number)
    finally:
        store.close()
    latency = time.perf_counter() - start

    hit, line_hit, matched = _judge(case, comments)
    result = CaseResult(
        case_id=case.id,
        layer=case.layer,
        hit=hit,
        line_hit=line_hit,
        posted=outcome.posted,
        matched=matched,
        latency_s=round(latency, 3),
        tokens=outcome.total_tokens,
        error=outcome.error,
    )
    return result, comments


def aggregate(results: list[CaseResult]) -> dict:
    """把逐条结果聚合为指标报告。"""
    bug_cases = [r for r in results if r.layer != "clean"]
    clean_cases = [r for r in results if r.layer == "clean"]

    def rate(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    latencies = sorted(r.latency_s for r in results)
    p95 = latencies[min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))] if latencies else 0.0
    total_posted = sum(r.posted for r in results)

    by_layer: dict[str, dict] = {}
    for layer in sorted({r.layer for r in results}):
        subset = [r for r in results if r.layer == layer]
        by_layer[layer] = {
            "cases": len(subset),
            "hit_rate": rate(sum(r.hit for r in subset), len(subset)),
            "posted": sum(r.posted for r in subset),
        }

    return {
        "generated_at": datetime.now().isoformat(),
        "metrics": {
            "file_hit_rate": rate(sum(r.hit for r in bug_cases), len(bug_cases)),
            "line_hit_rate": rate(sum(r.line_hit for r in bug_cases), len(bug_cases)),
            "precision_proxy": rate(sum(r.matched for r in results), total_posted),
            "false_positive_rate": rate(
                sum(1 for r in clean_cases if r.posted > 0), len(clean_cases)
            ),
            "p95_latency_s": round(p95, 3),
            "avg_tokens": round(sum(r.tokens for r in results) / len(results), 1)
            if results
            else 0,
            "total_tokens": sum(r.tokens for r in results),
        },
        "by_layer": by_layer,
        "cases": [asdict(r) for r in results],
    }


def _write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"report-{stamp}.json"
    md_path = out_dir / f"report-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    m = report["metrics"]
    lines = [
        "# pr-sentinel 评测报告",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 文件级检出率 | {m['file_hit_rate']:.2%} |",
        f"| 行级命中率 | {m['line_hit_rate']:.2%} |",
        f"| 精确率（代理） | {m['precision_proxy']:.2%} |",
        f"| 误报率（clean 组） | {m['false_positive_rate']:.2%} |",
        f"| p95 延迟 | {m['p95_latency_s']} s |",
        f"| 平均 token | {m['avg_tokens']} |",
        f"| 总 token | {m['total_tokens']} |",
        "",
        "## 分层结果",
        "",
        "| 层 | 用例数 | 检出率 | 评论数 |",
        "|---|---|---|---|",
    ]
    for layer, info in report["by_layer"].items():
        lines.append(
            f"| {layer} | {info['cases']} | {info['hit_rate']:.2%} | {info['posted']} |"
        )
    lines += ["", "## 用例明细", "", "| 用例 | 层 | 检出 | 评论 | 命中 | 错误 |",
              "|---|---|---|---|---|---|"]
    for c in report["cases"]:
        lines.append(
            f"| {c['case_id']} | {c['layer']} | {c['hit']} | {c['posted']} "
            f"| {c['matched']} | {c['error'] or '-'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


async def evaluate(
    cases: list[EvalCase],
    *,
    repo_root: Path,
    registry: ToolRegistry,
    llm: ChatModel,
    out_dir: Path,
    use_cache: bool = True,
) -> dict:
    """跑完整评测集，写报告，返回报告 dict。"""
    comments_dir = out_dir / "comments"
    comments_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    results: list[CaseResult] = []
    for case in cases:
        cache_file = cache_dir / f"{case.id}.json"
        if use_cache and cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            results.append(CaseResult(**cached["result"]))
            continue

        result, comments = await run_case(
            case,
            repo_root=repo_root,
            registry=registry,
            llm=llm,
            comments_dir=comments_dir,
        )
        cache_file.write_text(
            json.dumps(
                {"result": asdict(result), "comments": comments},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        results.append(result)

    report = aggregate(results)
    _write_report(report, out_dir)
    return report
