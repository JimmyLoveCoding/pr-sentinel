"""审查报告（汇总评论正文）的生成。

一条 review 的 body 长这样：
    ## pr-sentinel 审查报告
    风险等级：**major** · 发现 2 个问题（major × 1、minor × 1）

    <details>
    <summary>审查过程（4 步 · 36.2s · 5.1k tokens）</summary>
    - 第 1 步：`read_file(uploader.py)`
    - 第 2 步：`search_bug_history(upload KeyError)`
    </details>

行内评论单独挂在 comments 数组里，和这份报告同属一个 review。
"""

from __future__ import annotations

from collections import Counter

from app.review.findings import Finding


def risk_level(findings: list[Finding]) -> str:
    """取最高严重度作为整体风险等级；无发现为 clean。"""
    if any(f.severity.value == "blocker" for f in findings):
        return "blocker"
    if any(f.severity.value == "major" for f in findings):
        return "major"
    if findings:
        return "minor"
    return "clean"


def build_summary_body(
    findings: list[Finding],
    *,
    trace: list[dict],
    steps: int,
    total_tokens: int,
    elapsed_s: float,
    stopped_reason: str = "final",
) -> str:
    """生成汇总评论：风险等级 + 折叠的审查过程。"""
    lines = ["## pr-sentinel 审查报告", ""]

    if not findings:
        lines.append("风险等级：**clean** · 未发现问题。")
    else:
        counts = Counter(f.severity.value for f in findings)
        detail = "、".join(f"{severity} × {count}" for severity, count in counts.items())
        lines.append(
            f"风险等级：**{risk_level(findings)}** · 发现 {len(findings)} 个问题（{detail}）"
        )

    lines.append("")
    lines.append("<details>")
    lines.append(
        f"<summary>审查过程（{steps} 步 · {elapsed_s:.1f}s · {total_tokens} tokens "
        f"· 结束原因 {stopped_reason}）</summary>"
    )
    lines.append("")
    if trace:
        for item in trace:
            calls = item.get("tool_calls") or []
            if calls:
                parts = "；".join(
                    f"`{c.get('name')}`（{(c.get('args') or '')[:60]}）" for c in calls
                )
            else:
                parts = "模型回复（无工具调用）"
            lines.append(f"- 第 {item.get('step')} 步：{parts}")
    else:
        lines.append("- （无工具调用记录）")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)
