import asyncio
from pathlib import Path

from app.review.store import ReviewCommentStore
from app.tools.post_comment import make_post_review_comment_tool
from app.tools.registry import build_registry


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    return root


def test_post_summary_comment(tmp_path) -> None:
    store = ReviewCommentStore(tmp_path / "comments.db")
    tool = make_post_review_comment_tool(store, "org/app", 128)

    result = asyncio.run(tool.fn(body="总体风险：低。发现 2 个 minor 问题。", severity="summary"))

    assert result["status"] == "posted"
    assert result["comment"]["url"].startswith("mock://org/app/pull/128")
    store.close()


def test_post_inline_comment(tmp_path) -> None:
    store = ReviewCommentStore(tmp_path / "comments.db")
    tool = make_post_review_comment_tool(store, "org/app", 128)

    asyncio.run(
        tool.fn(
            body="L42 空指针风险：resp.json() 可能不含 url 字段。",
            severity="blocker",
            file_path="a.py",
            line=42,
        )
    )

    comments = store.list_for("org/app", 128)
    assert len(comments) == 1
    assert comments[0]["file_path"] == "a.py"
    assert comments[0]["line"] == 42
    assert comments[0]["severity"] == "blocker"
    store.close()


def test_post_comment_validation(tmp_path) -> None:
    store = ReviewCommentStore(tmp_path / "comments.db")
    tool = make_post_review_comment_tool(store, "org/app", 128)

    assert "error" in asyncio.run(tool.fn(body="   "))
    assert "error" in asyncio.run(tool.fn(body="x", severity="fatal"))
    assert "error" in asyncio.run(tool.fn(body="x", file_path="a.py"))  # 只有文件没有行号
    store.close()


def test_registry_with_comment_tool(tmp_path) -> None:
    root = make_repo(tmp_path)
    store = ReviewCommentStore(tmp_path / "comments.db")
    registry = build_registry(root, comment_store=store, repo="org/app", pr_number=42)

    names = {s["function"]["name"] for s in registry.schemas()}
    assert "post_review_comment" in names
    assert len(names) == 5  # 基础四件套 + 评论
    store.close()
