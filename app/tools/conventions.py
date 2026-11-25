"""search_conventions 工具：检索项目规范条款。"""

from __future__ import annotations

from app.conventions.store import ConventionStore
from app.tools.base import Tool


def make_search_conventions_tool(store: ConventionStore) -> Tool:
    async def search_conventions(query: str, top_k: int = 3) -> dict:
        if not query.strip():
            return {"error": "query 不能为空"}
        results = store.search(query, top_k=min(max(top_k, 1), 5))
        return {"query": query, "count": len(results), "results": results}

    return Tool(
        name="search_conventions",
        description=(
            "检索项目规范条款（CONTRIBUTING 与 docs 文档）。"
            "当需要判断改动是否违反项目约定、或在评论中引用规范出处时使用。"
            "返回来源文件、标题与条款正文。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "规范主题关键词，如 '超时 timeout' 或 '命名 规范'",
                },
                "top_k": {"type": "integer", "description": "返回条数，1-5，默认 3"},
            },
            "required": ["query"],
        },
        fn=search_conventions,
    )
