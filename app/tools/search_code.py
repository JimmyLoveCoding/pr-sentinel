"""search_code 工具：按关键字/符号在仓库里搜索定义与调用点。

审查 Agent 的"跨文件影响面"判断靠它：
"Is this function's return value checked elsewhere?" —— 搜一搜就知道了。
"""

from __future__ import annotations

from app.tools.base import Tool
from app.tools.repo_source import RepoSource


def make_search_code_tool(source: RepoSource) -> Tool:
    async def search_code(
        query: str, glob: str | None = None, max_results: int = 20
    ) -> dict:
        return source.search_code(query, glob=glob, max_results=max_results)

    return Tool(
        name="search_code",
        description=(
            "在仓库中搜索字符串或符号（函数名、变量名等），返回匹配的文件、行号和代码行。"
            "用于查找某个函数的定义在哪、哪些地方在调用它，判断改动的影响面。"
            "可选 glob 限定文件类型，如 '*.py'。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜索的字符串或符号名"},
                "glob": {"type": "string", "description": "可选的文件过滤，如 '*.py'"},
                "max_results": {"type": "integer", "description": "返回条数上限，默认 20"},
            },
            "required": ["query"],
        },
        fn=search_code,
    )
