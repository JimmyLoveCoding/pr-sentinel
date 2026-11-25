"""工具抽象：名称 + 描述 + JSON Schema + 异步执行函数。

工具是 Agent 的手脚。schema 写得好不好，直接决定工具路由准确率——
这是 D10–D12 评测迭代时最常改的地方。
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

ToolFn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolFn

    def openai_schema(self) -> dict[str, Any]:
        """转换为 OpenAI function calling 的工具描述。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重名: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """这个工具是否已注册（用于岗位工具清单与注册表取交集）。"""
        return name in self._tools

    def schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        tools = self._tools.values() if names is None else [self._tools[n] for n in names]
        return [t.openai_schema() for t in tools]
