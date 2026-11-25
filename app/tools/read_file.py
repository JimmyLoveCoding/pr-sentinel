"""read_file 工具：读取仓库文件内容（可指定行范围）。

做成"工厂函数"的原因：工具需要"记住"自己操作的是哪个仓库（数据源），
但 LLM 只能传 schema 里定义的参数（path / start_line / end_line）。
所以先由外部把 source 传进工厂，工厂返回一个"已经记住 source"的工具。
——闭包捕获依赖，等价于 Java 里 lambda 捕获一个 final 变量。
"""

from __future__ import annotations

from app.tools.base import Tool
from app.tools.repo_source import RepoSource


def make_read_file_tool(source: RepoSource) -> Tool:
    async def read_file(
        path: str, start_line: int | None = None, end_line: int | None = None
    ) -> dict:
        return source.read_file(path, start_line=start_line, end_line=end_line)

    return Tool(
        name="read_file",
        description=(
            "读取仓库中某个文件的完整内容，或只读指定行范围（行号从 1 开始）。"
            "当 diff 上下文不足以判断问题（如需要看函数开头有没有判空、类的全貌）时使用。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对仓库根目录的文件路径，如 'src/uploader.py'",
                },
                "start_line": {"type": "integer", "description": "起始行号（可选，从 1 开始）"},
                "end_line": {"type": "integer", "description": "结束行号（可选，包含该行）"},
            },
            "required": ["path"],
        },
        fn=read_file,
    )
