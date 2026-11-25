import pytest

from app.tools.base import Tool, ToolRegistry


async def _echo(text: str) -> dict:
    return {"text": text}


def _make_tool() -> Tool:
    return Tool(
        name="echo",
        description="回显输入（仅测试用）",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        fn=_echo,
    )


def test_register_and_get() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool())
    assert registry.get("echo").name == "echo"


def test_openai_schema_shape() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool())
    (schema,) = registry.schemas()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert schema["function"]["parameters"]["required"] == ["text"]


def test_duplicate_name_rejected() -> None:
    registry = ToolRegistry()
    registry.register(_make_tool())
    with pytest.raises(ValueError):
        registry.register(_make_tool())


def test_unknown_tool() -> None:
    registry = ToolRegistry()
    with pytest.raises(KeyError):
        registry.get("nope")
