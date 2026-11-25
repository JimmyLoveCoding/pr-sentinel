"""手写 ReAct 循环：Agent 的心脏。

模型只会"说"它想调什么工具（tool_calls），循环替它真去调、把结果塞回对话、
再问下一轮——直到模型不再要工具，说出最终答案。

一轮循环：messages → client.chat(tools) → 有 tool_calls？执行→回填→继续 : 结束

三个安全阀（评测里会专门测）：
- max_steps：步数上限，防死循环；
- 工具异常回传：工具报错作为工具结果返回给模型，不中断循环；
- 循环检测：同工具+同参数连续出现 3 次，判定模型在打转，强制收束。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.client import LLMClient, LLMResponse
from app.tools.base import ToolRegistry

_MAX_REPEATS = 3#同一个工具、同样的参数，连续出现几次就判定在打转
_RESULT_SNIPPET = 2000  # 工具结果回填消息时的截断长度


class ChatModel(Protocol):
    """循环对模型的唯一要求：实现 async chat()。FakeLLM 与 LLMClient 都满足。"""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse: ...


@dataclass
class AgentState:#循环从第一轮到最后一轮干的所有事，都记在这个对象上，跑完作为结案材料一起交回去
    messages: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    total_tokens: int = 0
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResult:#最后的结果
    final_answer: str
    state: AgentState
    stopped_reason: str  # "final" | "max_steps" | "loop_detected"


def _tool_result_message(call_id: str, result: Any) -> dict[str, Any]:#把工具执行结果封装成消息，塞回对话里
    """工具结果 → OpenAI 协议里的 tool 消息（内容必须是字符串）。"""
    text = json.dumps(result, ensure_ascii=False, default=str)
    return {"role": "tool", "tool_call_id": call_id, "content": text[:_RESULT_SNIPPET]}


async def run_agent(
    task: str,
    registry: ToolRegistry,
    *,
    llm: ChatModel | None = None,
    system_prompt: str = "你是代码评审助手。",
    max_steps: int = 8,# 最大步数，防死循环
    tool_names: list[str] | None = None,  # 按岗位裁剪工具；None = 全部
) -> AgentResult:
    model = llm or LLMClient()
    state = AgentState(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
    )
    # 岗位工具清单 ∩ 注册表实际有的工具（可选库未配置时，对应工具自动缺席）
    if tool_names is not None:
        tool_names = [n for n in tool_names if registry.has(n)]
    tools = registry.schemas(tool_names)  # 只把岗位允许的工具发给模型
    recent_calls: list[tuple[str, str]] = []  # (工具名, 参数) 最近签名的滑动窗口

    while state.steps < max_steps:
        state.steps += 1
        response = await model.chat(state.messages, tools=tools)
        state.total_tokens += int(response.usage.get("total_tokens", 0))
        state.trace.append(
            {
                "step": state.steps,
                "tool_calls": [
                    {
                        "name": c.get("function", {}).get("name"),
                        "args": (c.get("function", {}).get("arguments") or "")[:120],
                    }
                    for c in response.tool_calls
                ],
                "usage": response.usage,
            }
        )

        if not response.tool_calls:
            return AgentResult(
                final_answer=response.content or "",
                state=state,
                stopped_reason="final",
            )

        # 把模型这条带 tool_calls 的回复原样记入对话
        state.messages.append(
            {
                "role": "assistant",
                "content": response.content,
                "tool_calls": response.tool_calls,
            }
        )

        for call in response.tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments") or "{}"
            call_id = call.get("id", f"call_{state.steps}")

            # 循环检测：同工具+同参数连续出现，视为在打转
            signature = (name, raw_args)
            recent_calls.append(signature)
            if len(recent_calls) > _MAX_REPEATS:
                recent_calls.pop(0)
            if len(recent_calls) == _MAX_REPEATS and len(set(recent_calls)) == 1:
                return AgentResult(
                    final_answer=f"检测到重复调用 {name}，强制收束。",
                    state=state,
                    stopped_reason="loop_detected",
                )

            result = await _execute_tool(registry, name, raw_args)
            state.messages.append(_tool_result_message(call_id, result))

    return AgentResult(
        final_answer="达到最大步数仍未得出结论。",
        state=state,
        stopped_reason="max_steps",
    )


async def _execute_tool(registry: ToolRegistry, name: str, raw_args: str) -> Any:#在调用工具前，先把参数解析成 JSON 对象，然后调用工具函数，并捕获异常，确保不会中断循环
    """执行一个工具调用；任何异常都转成 {"error": ...} 回传，绝不炸循环。"""
    try:
        tool = registry.get(name)
    except KeyError:
        return {"error": f"未知工具: {name}"}
    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            return {"error": f"参数必须是 JSON 对象，收到: {type(args).__name__}"}
    except json.JSONDecodeError as exc:
        return {"error": f"参数无法解析为 JSON: {exc}"}
    try:
        return await tool.fn(**args)
    except TypeError as exc:
        return {"error": f"参数与工具 schema 不符: {exc}"}
    except Exception as exc:  # 工具内部任何异常，都作为结果回传
        return {"error": f"工具执行失败: {type(exc).__name__}: {exc}"}
