"""审查任务书组装：把 PR 信息和 diff 拼成给 Agent 的 user 消息。

设计说明（和需求文档早期的"四路上下文预组装"不同）：
我们走的是"拉取式"——任务书里只给 diff 和规则，完整文件、历史 bug、
规范条款由模型按需通过工具自己拉。好处是省 token、由模型决定审查深度；
代价是模型要"知道去拉"，这靠任务书末尾的明确指引。
"""

from __future__ import annotations

MAX_DIFF_CHARS = 30_000

REVIEW_PROMPT_TEMPLATE = """你是一名资深代码审查员，正在审查一个 Pull Request。

## PR 信息
- 仓库：{repo}
- PR：#{pr_number} {title}
- 提交：{head_sha}

## 改动 diff
```diff
{diff}
```

## 审查要求
1. 逐条检查 diff 中的新增行（+ 行），关注四类问题：
   - correctness：正确性缺陷（空值、边界、资源泄漏、异常吞噬、并发竞态）
   - regression：与历史 bug 相似的模式（用 search_bug_history 查证）
   - security：硬编码密钥、注入风险、危险调用
   - maintainability：重复代码、命名、复杂度、与项目规范偏离（用 run_linters / search_conventions 查证）
2. 上下文不足时，用 read_file / search_code 查看完整文件和调用点。
3. 每条发现必须带证据（引用的代码、历史提交 SHA 或规范条款）；没有证据的猜测不要报。
4. 严重度定义：blocker（必然出故障/安全漏洞）、major（高概率出问题）、minor（建议改进）。

## 输出格式
完成审查后，你的最终回复必须且只能是一个 JSON 数组：
[{{"file": "相对路径", "line": 1, "severity": "blocker|major|minor",
  "category": "correctness|regression|security|maintainability",
  "message": "问题描述", "evidence": "证据", "suggestion": "修复建议"}}]
没有发现问题时输出 []。
"""


def build_review_task(
    *,
    repo: str,
    pr_number: int,
    title: str,
    head_sha: str,
    diff_text: str,
    max_diff_chars: int = MAX_DIFF_CHARS,
) -> str:
    """组装完整的审查任务书（run_agent 的 task 参数）。"""
    if len(diff_text) > max_diff_chars:
        diff_text = (
            diff_text[:max_diff_chars]
            + "\n... [diff 已截断；完整改动请用 list_changed_files 和 read_file 查看]"
        )
    return REVIEW_PROMPT_TEMPLATE.format(
        repo=repo,
        pr_number=pr_number,
        title=title or "",
        head_sha=head_sha,
        diff=diff_text,
    )
