"""post_review_comment 工具（mock 版）：发布审查评论。

全系统唯一带副作用的工具。两个安全设计：
- repo / PR 号由装配时注入，模型无从指定 —— 不可能把评论发到别的 PR；
- 只有一种副作用：写评论。没有关 PR、打标签、合代码的权限。

行内评论 = 提供 file_path + line；汇总评论 = 两者都省略。
M9 换成真实 GitHub Review API 时，只替换 ReviewCommentStore。
"""

from __future__ import annotations

from app.review.store import ReviewCommentStore
from app.tools.base import Tool

_SEVERITIES = ("blocker", "major", "minor", "summary")


def make_post_review_comment_tool(
    store: ReviewCommentStore, repo: str, pr_number: int
) -> Tool:
    async def post_review_comment(
        body: str,
        severity: str = "minor",
        file_path: str | None = None,
        line: int | None = None,
    ) -> dict:
        if not body.strip():
            return {"error": "body 不能为空"}
        if severity not in _SEVERITIES:
            return {"error": f"severity 必须是 {_SEVERITIES} 之一"}
        if (file_path is None) != (line is None):
            return {
                "error": "file_path 和 line 必须同时提供（行内评论）或同时省略（汇总评论）"
            }
        comment = store.add(
            repo=repo,
            pr_number=pr_number,
            file_path=file_path,
            line=line,
            severity=severity,
            body=body.strip(),
        )
        return {"status": "posted", "comment": comment}

    return Tool(
        name="post_review_comment",
        description=(
            "把一条审查评论发布到当前 PR。"
            "提供 file_path 和 line 表示行内评论（line 用新文件真实行号）；"
            "都省略表示汇总评论。severity 取 blocker / major / minor / summary。"
            "每条评论必须包含证据（代码引用、历史提交或规范条款）。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string", "description": "评论文本（markdown），需包含证据与修复建议"},
                "severity": {
                    "type": "string",
                    "enum": list(_SEVERITIES),
                    "description": "严重度：blocker / major / minor / summary",
                },
                "file_path": {"type": "string", "description": "行内评论的文件相对路径（可选）"},
                "line": {"type": "integer", "description": "行内评论的行号，新文件真实行号（可选）"},
            },
            "required": ["body"],
        },
        fn=post_review_comment,
    )
