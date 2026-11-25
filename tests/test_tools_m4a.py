import asyncio
import subprocess
from pathlib import Path

from app.tools.list_changed_files import make_list_changed_files_tool
from app.tools.read_file import make_read_file_tool
from app.tools.registry import build_registry
from app.tools.repo_source import LocalRepoSource


def make_repo(tmp_path: Path) -> Path:
    """造一个真 git 仓库：一个文件 + 第一个提交。"""
    root = tmp_path / "repo"
    root.mkdir()
    run = lambda *args: subprocess.run(args, cwd=root, check=True, capture_output=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "tester")
    (root / "uploader.py").write_text("line40\nline41\nline42\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "init")
    return root


def test_read_file_range(tmp_path) -> None:
    root = make_repo(tmp_path)
    tool = make_read_file_tool(LocalRepoSource(root))

    result = asyncio.run(tool.fn(path="uploader.py", start_line=2, end_line=3))
    assert result["content"] == "line41\nline42"
    assert result["total_lines"] == 3


def test_read_file_rejects_traversal(tmp_path) -> None:
    root = make_repo(tmp_path)
    tool = make_read_file_tool(LocalRepoSource(root))

    result = asyncio.run(tool.fn(path="../../etc/passwd"))
    assert "error" in result


def test_read_file_missing(tmp_path) -> None:
    root = make_repo(tmp_path)
    tool = make_read_file_tool(LocalRepoSource(root))

    result = asyncio.run(tool.fn(path="nope.py"))
    assert "error" in result


def test_list_changed_files(tmp_path) -> None:
    root = make_repo(tmp_path)
    (root / "uploader.py").write_text(
        "line40\nline41 changed\nline42\nline43\n", encoding="utf-8"
    )
    (root / "new.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True, capture_output=True)

    tool = make_list_changed_files_tool(root)
    result = asyncio.run(tool.fn(base="HEAD~1", head="HEAD"))

    by_path = {f["path"]: f for f in result["files"]}
    assert set(by_path) == {"uploader.py", "new.md"}
    assert by_path["new.md"]["additions"] == 1
    # git 按最小改动计算：line41 改 1 行（1 增 1 删），line43 新增 1 行
    assert by_path["uploader.py"]["additions"] == 2
    assert by_path["uploader.py"]["deletions"] == 1


def test_registry_has_tools(tmp_path) -> None:
    root = make_repo(tmp_path)
    registry = build_registry(root)
    names = {s["function"]["name"] for s in registry.schemas()}
    assert names == {"read_file", "search_code", "list_changed_files", "run_linters"}
