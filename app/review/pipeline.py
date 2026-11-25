"""审查管线：一张工单从 diff 到评论的全流程。

工序：
    取 diff → 组装任务书 → Agent 循环 → 解析 Finding → 护栏
    → 生成汇总报告 + 行内评论 → 一次发布 → trace 落盘

设计说明：
- 审查员（reviewer）只读；评论由管线在护栏之后统一发布——护栏在模型控制之外；
- 评论形态：一条汇总 review（正文含折叠的审查过程）+ 多条行内评论；
- 每次运行（包括失败）都把 trace 落盘到 data/traces/{ticket_id}.json；
- 任何一步失败都返回 ok=False + error，由 Worker 按重试策略处理。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.agent.context import build_review_task
from app.agent.loop import ChatModel, run_agent
from app.agent.worker import WORKER_SPECS
from app.core.git import git_diff_text
from app.review.findings import Finding, parse_findings
from app.review.guardrails import apply_guardrails
from app.review.store import CommentSink
from app.review.summary import build_summary_body
from app.review.traces import save_trace
from app.tasks.models import Ticket
from app.tools.base import ToolRegistry


@dataclass
class ReviewOutcome:
    """一次审查的结案报告：成败、发出几条评论、解析错误、停止原因、花费、trace 路径。"""

    ok: bool
    posted: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_reason: str = "final"
    total_tokens: int = 0
    error: str = ""
    trace_path: str = ""


def format_comment(finding: Finding) -> str:
    """把 Finding 拼成一条 markdown 评论：问题 + 证据 + 建议。"""
    parts = [finding.message]  # 第一段：问题描述
    if finding.evidence:  # 有证据就追加，让每条评论都可追溯
        parts.append(f"**证据**：{finding.evidence}")
    if finding.suggestion:  # 有建议就追加，让评论可执行
        parts.append(f"**建议**：{finding.suggestion}")
    return "\n\n".join(parts)  # 段落之间空一行，markdown 排版


def _finish(
    ticket: Ticket,
    outcome: ReviewOutcome,
    *,
    trace: list[dict] | None = None,
    steps: int = 0,
    tokens: int = 0,
    elapsed: float = 0.0,
) -> ReviewOutcome:
    """收尾：落盘 trace（含失败运行），返回 outcome。"""
    outcome.trace_path = save_trace(
        ticket.id,
        trace=trace or [],
        ok=outcome.ok,
        steps=steps,
        total_tokens=tokens,
        stopped_reason=outcome.stopped_reason,
        posted=outcome.posted,
        error=outcome.error,
        elapsed_s=elapsed,
    )
    return outcome


async def review_ticket(
    ticket: Ticket,
    *,
    repo_root: Path,
    registry: ToolRegistry,
    comment_store: CommentSink,
    llm: ChatModel,
    base_ref: str | None = None,
    max_steps: int = 8,
) -> ReviewOutcome:
    """执行一张工单的完整审查流程。"""
    started = time.perf_counter()
    # 对比基准的优先级：显式参数 > 工单里的真 base_sha > 回退 head~1（mock/MVP）
    base = base_ref or ticket.base_sha or f"{ticket.head_sha}~1"
    try:  # ② 取这次改动（base..head）的原始 diff；git 失败时带上真实原因
        diff_text = git_diff_text(repo_root, base, ticket.head_sha)
    except RuntimeError as exc:
        return _finish(
            ticket,
            ReviewOutcome(ok=False, error=f"获取 diff 失败: {exc}"),
            elapsed=time.perf_counter() - started,
        )
    if diff_text is None:  # 仓库不存在 / git 不可用 / 超时
        return _finish(
            ticket,
            ReviewOutcome(ok=False, error=f"获取 diff 失败: {base}..{ticket.head_sha}"),
            elapsed=time.perf_counter() - started,
        )
    if not diff_text.strip():  # ③ 空 diff（没有实际改动）：直接算审完，不浪费模型调用
        return _finish(
            ticket,
            ReviewOutcome(ok=True, posted=0),
            elapsed=time.perf_counter() - started,
        )

    spec = WORKER_SPECS.get(ticket.worker, WORKER_SPECS["reviewer"])  # ④ 取岗位说明书
    task = build_review_task(  # ⑤ 组装任务书：PR 信息 + diff + 审查规则 + 输出格式
        repo=ticket.repo,
        pr_number=ticket.pr_number,
        title=ticket.title,
        head_sha=ticket.head_sha,
        diff_text=diff_text,
    )
    result = await run_agent(  # ⑥ 跑循环：模型调工具、循环回填，直到给出最终答案
        task,
        registry,
        llm=llm,
        system_prompt=spec.system_prompt,
        max_steps=max_steps,
        tool_names=list(spec.tool_names),
    )
    elapsed = time.perf_counter() - started

    if result.stopped_reason != "final":  # ⑦ 收束检查：打转/超步数的运行不算数
        return _finish(
            ticket,
            ReviewOutcome(
                ok=False,
                stopped_reason=result.stopped_reason,
                total_tokens=result.state.total_tokens,
                error=f"审查未完成: {result.stopped_reason}",
            ),
            trace=result.state.trace,
            steps=result.state.steps,
            tokens=result.state.total_tokens,
            elapsed=elapsed,
        )

    findings, parse_errors = parse_findings(result.final_answer)  # ⑧ 宽容拆包 + 严格验收
    final = apply_guardrails(findings)  # ⑨ 四道护栏：脱敏 → 排序 → 去重 → 截断

    summary_body = build_summary_body(  # ⑩ 汇总报告：风险等级 + 折叠的审查过程
        final,
        trace=result.state.trace,
        steps=result.state.steps,
        total_tokens=result.state.total_tokens,
        elapsed_s=elapsed,
    )
    comments = [
        {
            "file_path": f.file,
            "line": f.line,
            "severity": f.severity.value,
            "body": format_comment(f),
        }
        for f in final
    ]
    try:  # ⑪ 一次发布：汇总 review + 行内评论（护栏之后才发，模型无法绕过）
        comment_store.publish_review(
            repo=ticket.repo,
            pr_number=ticket.pr_number,
            summary_body=summary_body,
            comments=comments,
        )
    except Exception as exc:  # 发布失败按失败上报，避免"工单成功但评论没发"
        return _finish(
            ticket,
            ReviewOutcome(
                ok=False,
                total_tokens=result.state.total_tokens,
                error=f"评论发布失败: {type(exc).__name__}: {exc}",
            ),
            trace=result.state.trace,
            steps=result.state.steps,
            tokens=result.state.total_tokens,
            elapsed=time.perf_counter() - started,
        )

    return _finish(  # ⑫ 结案：评论数、解析错误、token 花费、trace 路径
        ticket,
        ReviewOutcome(
            ok=True,
            posted=len(final),
            errors=parse_errors,
            stopped_reason="final",
            total_tokens=result.state.total_tokens,
        ),
        trace=result.state.trace,
        steps=result.state.steps,
        tokens=result.state.total_tokens,
        elapsed=time.perf_counter() - started,
    )
