import asyncio
import subprocess
from pathlib import Path

from app.bughistory.collector import collect_bug_commits
from app.bughistory.store import BugHistoryStore, ingest_repo
from app.tools.bug_history import make_search_bug_history_tool
from app.tools.registry import build_registry


def make_repo(tmp_path: Path) -> Path:
    """造一个包含 4 个提交的小仓库：2 个 bug 修复 + 2 个普通提交。"""
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args: str) -> None:
        subprocess.run(args, cwd=root, check=True, capture_output=True)

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "tester")

    (root / "uploader.py").write_text("def upload():\n    return None\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "init project")

    (root / "uploader.py").write_text(
        "def upload():\n    return {}\n\ndef retry():\n    pass\n", encoding="utf-8"
    )
    run("git", "add", ".")
    run("git", "commit", "-qm", "fix: handle KeyError in upload retry")

    (root / "page.py").write_text("print('hi')\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "feat: add new page")

    (root / "uploader.py").write_text("def upload():\n    return {'url': ''}\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "修复：上传结果空指针")
    return root


def test_collect_only_bug_commits(tmp_path) -> None:
    root = make_repo(tmp_path)
    commits = collect_bug_commits(root)

    assert len(commits) == 2
    messages = {c.message for c in commits}
    assert any("KeyError" in m for m in messages)
    assert any("修复" in m for m in messages)
    assert all("uploader.py" in c.files for c in commits)
    assert all(c.snippet for c in commits)  # patch 片段非空


def test_ingest_and_search(tmp_path) -> None:
    root = make_repo(tmp_path)
    store = BugHistoryStore(tmp_path / "bugs.db")

    assert ingest_repo(root, store) == 2
    assert store.count() == 2

    hits = store.search("KeyError")
    assert hits
    assert "KeyError" in hits[0]["message"]

    zh_hits = store.search("空指针")
    assert zh_hits
    assert "修复" in zh_hits[0]["message"]

    assert store.search("完全无关的词组xyz") == []
    store.close()


def test_ingest_idempotent(tmp_path) -> None:
    root = make_repo(tmp_path)
    store = BugHistoryStore(tmp_path / "bugs.db")

    ingest_repo(root, store)
    ingest_repo(root, store)
    assert store.count() == 2  # 同一 sha 重复入库只保留一份
    store.close()


def test_tool_interface(tmp_path) -> None:
    root = make_repo(tmp_path)
    store = BugHistoryStore(tmp_path / "bugs.db")
    ingest_repo(root, store)

    tool = make_search_bug_history_tool(store)
    result = asyncio.run(tool.fn(query="upload KeyError", top_k=3))
    assert result["count"] >= 1
    assert {"sha", "date", "message", "files", "snippet", "score"} <= set(result["results"][0])

    empty = asyncio.run(tool.fn(query="  "))
    assert "error" in empty
    store.close()


def test_registry_with_bug_store(tmp_path) -> None:
    root = make_repo(tmp_path)
    store = BugHistoryStore(tmp_path / "bugs.db")
    registry = build_registry(root, bug_store=store)
    names = {s["function"]["name"] for s in registry.schemas()}

    assert names == {
        "read_file",
        "search_code",
        "list_changed_files",
        "run_linters",
        "search_bug_history",
    }
    store.close()
