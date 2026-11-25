"""search_bug_history 工具：检索历史 bug 修复，判断是否重蹈覆辙。

这是审查官的"记忆"——模型看到可疑改动时，可以用问题关键词（异常名、
函数名、改动主题）来查历史相似事故，把证据引用进评论。
"""

from __future__ import annotations

from app.bughistory.store import BugHistoryStore
from app.tools.base import Tool


def make_search_bug_history_tool(store: BugHistoryStore) -> Tool:
    async def search_bug_history(query: str, top_k: int = 5) -> dict:
        if not query.strip():#输入检查，如果 query 为空或仅包含空白字符，则返回错误信息
            return {"error": "query 不能为空"}
        results = store.search(query, top_k=min(max(top_k, 1), 10))#查库的结果，top_k 限制在 1 到 10 之间
        return {"query": query, "count": len(results), "results": results}

    return Tool(
        name="search_bug_history",
        description=(
            "检索仓库历史中修过的 bug。当怀疑本次改动在重复历史问题时使用，"
            "传入问题关键词（异常名、函数名、改动主题，中英文均可）。"
            "返回修复提交的 SHA、日期、说明、涉及文件和 patch 片段，可作为评论证据引用。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词，如 'upload KeyError' 或 '空指针 重试'"},
                "top_k": {"type": "integer", "description": "返回条数，1-10，默认 5"},
            },
            "required": ["query"],
        },
        fn=search_bug_history,
    )
