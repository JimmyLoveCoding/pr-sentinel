"""LLM 客户端封装：OpenAI 兼容协议（DeepSeek / 通义 DashScope 等）。

原则：不依赖任何 Agent 框架，只做一个薄薄的 HTTP 客户端。
M5 用它驱动手写 Agent 循环；流式版本在 M9 配合 SSE 实现。
"""

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings


@dataclass
class LLMResponse:#这个数据类用于封装语言模型的响应信息，包括响应内容、工具调用信息、使用情况和模型名称。
    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def chat(#这个方法是定义一个异步函数，用于与语言模型进行对话。它接受一系列参数，包括消息列表、工具列表、模型名称和温度设置，并返回一个 LLMResponse 对象，包含模型的响应内容、工具调用信息、使用情况和模型名称。
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """一次非流式调用。流式版本在 M9 实现（配合 SSE）。"""
        if not self.settings.openai_api_key:
            raise RuntimeError("未配置 OPENAI_API_KEY：请复制 .env.example 为 .env 并填写")

        payload: dict[str, Any] = {
            "model": model or self.settings.model_strong,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            resp = await client.post(
                f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]
        return LLMResponse(
            content=choice.get("content"),
            tool_calls=choice.get("tool_calls") or [],
            usage=data.get("usage") or {},
            model=data.get("model", payload["model"]),
        )
