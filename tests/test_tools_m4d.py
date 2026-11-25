import asyncio
from pathlib import Path

import pytest

from app.conventions.collector import collect_sections
from app.conventions.store import ConventionStore, ingest_repo
from app.tools.conventions import make_search_conventions_tool
from app.tools.linters import make_run_linters_tool


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "CONTRIBUTING.md").write_text(
        "# 代码风格\n\n网络请求必须设置超时（timeout），禁止裸调用。\n\n"
        "# 提交规范\n\n提交消息使用 fix: / feat: 前缀。\n",
        encoding="utf-8",
    )
    docs = root / "docs"
    docs.mkdir()
    (docs / "style.md").write_text("# 命名\n\n变量使用 snake_case。\n", encoding="utf-8")
    return root


def test_collect_sections(tmp_path) -> None:
    sections = collect_sections(make_repo(tmp_path))

    assert len(sections) == 3
    headings = {s.heading for s in sections}
    assert {"代码风格", "提交规范", "命名"} <= headings


def test_convention_search_and_tool(tmp_path) -> None:
    root = make_repo(tmp_path)
    store = ConventionStore(tmp_path / "conv.db")
    assert ingest_repo(root, store) == 3

    hits = store.search("超时 timeout")
    assert hits
    assert hits[0]["heading"] == "代码风格"

    tool = make_search_conventions_tool(store)
    result = asyncio.run(tool.fn(query="snake_case 命名"))
    assert result["count"] >= 1
    assert "source" in result["results"][0]
    store.close()


def test_linters_reports_findings(tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / "bad.py").write_text("import os\nprint('hi')\n", encoding="utf-8")
    tool = make_run_linters_tool(root)

    result = asyncio.run(tool.fn(files=["bad.py"]))
    if "note" in result:  # ruff 不可用时走 fail-open 分支
        pytest.skip(result["note"])
    assert result["count"] >= 1

    # 不同版本 ruff 默认规则不同，不假设顺序：只要求 F401 在结果中
    hit = next(f for f in result["findings"] if f["rule_id"] == "F401")
    assert hit["file"] == "bad.py"
    assert hit["line"] == 1


def test_linters_fail_open(monkeypatch, tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("app.tools.linters.shutil.which", lambda _: None)

    tool = make_run_linters_tool(root)
    result = asyncio.run(tool.fn(files=["ok.py"]))
    assert result["findings"] == []
    assert "linters_unavailable" in result["note"]


def test_linters_rejects_bad_paths(tmp_path) -> None:
    root = make_repo(tmp_path)
    tool = make_run_linters_tool(root)

    result = asyncio.run(tool.fn(files=["../outside.py"]))
    assert "error" in result
