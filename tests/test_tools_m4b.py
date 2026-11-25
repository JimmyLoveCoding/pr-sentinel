import asyncio
import subprocess
from pathlib import Path

from app.tools.repo_source import LocalRepoSource
from app.tools.search_code import make_search_code_tool


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "uploader.py").write_text(
        "def upload(file):\n    return file\n", encoding="utf-8"
    )
    (root / "app.py").write_text(
        "from uploader import upload\nupload(f)\n", encoding="utf-8"
    )
    (root / "README.md").write_text("how to upload a file\n", encoding="utf-8")
    (root / "many.txt").write_text("alpha\n" * 5, encoding="utf-8")
    return root


def test_search_across_files(tmp_path) -> None:
    tool = make_search_code_tool(LocalRepoSource(make_repo(tmp_path)))
    result = asyncio.run(tool.fn(query="upload"))

    files = {m["file"] for m in result["matches"]}
    assert "uploader.py" in files
    assert "app.py" in files
    assert result["count"] >= 2


def test_search_line_numbers(tmp_path) -> None:
    tool = make_search_code_tool(LocalRepoSource(make_repo(tmp_path)))
    result = asyncio.run(tool.fn(query="def upload"))

    hit = next(m for m in result["matches"] if m["file"] == "uploader.py")
    assert hit["line"] == 1


def test_search_glob_filter(tmp_path) -> None:
    tool = make_search_code_tool(LocalRepoSource(make_repo(tmp_path)))
    result = asyncio.run(tool.fn(query="upload", glob="*.md"))

    assert result["matches"]
    assert all(m["file"].endswith(".md") for m in result["matches"])


def test_search_max_results(tmp_path) -> None:
    tool = make_search_code_tool(LocalRepoSource(make_repo(tmp_path)))
    result = asyncio.run(tool.fn(query="alpha", max_results=2))

    assert result["count"] == 2
    assert result["truncated"] is True
