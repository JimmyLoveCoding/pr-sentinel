import asyncio
import json

from app.agent.loop import run_agent
from app.llm.client import LLMResponse
from app.tools.base import Tool, ToolRegistry


class FakeLLM:
    """按剧本回话的假模型：scripts 按顺序返回，用完则重复最后一条。"""

    def __init__(self, scripts: list[LLMResponse]) -> None:
        self.scripts = scripts
        self.calls = 0
        self.seen_tools: list[list[dict] | None] = []

    async def chat(self, messages, *, tools=None, model=None, temperature=0.0):
        self.seen_tools.append(tools)
        script = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        return script


def text_response(content: str, tokens: int = 10) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], usage={"total_tokens": tokens})


def tool_call_response(name: str, args: dict, call_id: str = "c1") -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
        usage={"total_tokens": 10},
    )


def make_registry(fail: bool = False):
    executed: list[str] = []

    async def echo(text: str) -> dict:
        if fail:
            raise RuntimeError("boom")
        executed.append(text)
        return {"text": text}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="回显输入",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            fn=echo,
        )
    )
    return registry, executed


def tool_messages(result) -> list[dict]:
    return [m for m in result.state.messages if m.get("role") == "tool"]


def test_final_without_tools() -> None:
    llm = FakeLLM([text_response("审查完成，无问题。")])
    registry, _ = make_registry()

    result = asyncio.run(run_agent("审一下", registry, llm=llm))

    assert result.stopped_reason == "final"
    assert result.final_answer == "审查完成，无问题。"
    assert result.state.steps == 1
    assert llm.seen_tools[0] is not None  # 工具清单确实传给了模型


def test_tool_roundtrip() -> None:
    llm = FakeLLM(
        [tool_call_response("echo", {"text": "hi"}), text_response("完成")]
    )
    registry, executed = make_registry()

    result = asyncio.run(run_agent("审一下", registry, llm=llm))

    assert executed == ["hi"]  # 工具真的被执行
    assert result.stopped_reason == "final"
    assert result.state.steps == 2
    tool_msgs = tool_messages(result)
    assert len(tool_msgs) == 1
    assert "hi" in tool_msgs[0]["content"]  # 结果回填进了对话


def test_unknown_tool_becomes_error() -> None:
    llm = FakeLLM([tool_call_response("nope", {}), text_response("完成")])
    registry, _ = make_registry()

    result = asyncio.run(run_agent("审一下", registry, llm=llm))

    assert "未知工具" in tool_messages(result)[0]["content"]
    assert result.stopped_reason == "final"  # 循环没被打断


def test_tool_exception_becomes_error() -> None:
    llm = FakeLLM([tool_call_response("echo", {"text": "hi"}), text_response("完成")])
    registry, _ = make_registry(fail=True)

    result = asyncio.run(run_agent("审一下", registry, llm=llm))

    assert "工具执行失败" in tool_messages(result)[0]["content"]


def test_bad_json_arguments() -> None:
    bad_call = LLMResponse(
        content=None,
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "echo", "arguments": "{not json"},
            }
        ],
        usage={"total_tokens": 5},
    )
    llm = FakeLLM([bad_call, text_response("完成")])
    registry, _ = make_registry()

    result = asyncio.run(run_agent("审一下", registry, llm=llm))

    assert "无法解析" in tool_messages(result)[0]["content"]


def test_max_steps_guard() -> None:
    class CountingLLM:
        """每轮都调工具但参数不同——不是打转，只是活没干完。"""

        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, *, tools=None, model=None, temperature=0.0):
            self.calls += 1
            return tool_call_response("echo", {"text": f"v{self.calls}"})

    registry, _ = make_registry()

    result = asyncio.run(run_agent("审一下", registry, llm=CountingLLM(), max_steps=3))

    assert result.stopped_reason == "max_steps"
    assert result.state.steps == 3


def test_loop_detected() -> None:
    llm = FakeLLM([tool_call_response("echo", {"text": "same"})])
    registry, _ = make_registry()

    result = asyncio.run(run_agent("审一下", registry, llm=llm, max_steps=10))

    assert result.stopped_reason == "loop_detected"
    assert result.state.steps == 3  # 第三次出现相同调用时收束


def test_token_accumulation() -> None:
    llm = FakeLLM(
        [tool_call_response("echo", {"text": "hi"}), text_response("完成", tokens=25)]
    )
    registry, _ = make_registry()

    result = asyncio.run(run_agent("审一下", registry, llm=llm))

    assert result.state.total_tokens == 35  # 10 + 25
