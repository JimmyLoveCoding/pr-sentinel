import json

import httpx
import pytest

from app.config import Settings
from app.github.client import GitHubCommentClient


def make_client(handler) -> GitHubCommentClient:
    """测试专用：用 httpx.MockTransport 拦截网络，验证请求构造是否正确。"""
    return GitHubCommentClient(
        settings=Settings(github_token="t0ken"),
        transport=httpx.MockTransport(handler),
    )


def test_inline_comment_posts_review() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            201, json={"id": 1, "html_url": "https://github.com/org/app/pull/1#r1"}
        )

    client = make_client(handler)
    result = client.add(
        repo="org/app",
        pr_number=1,
        file_path="a.py",
        line=42,
        severity="major",
        body="L42 有风险",
    )

    assert seen["url"] == "https://api.github.com/repos/org/app/pulls/1/reviews"
    payload = seen["body"]
    assert payload["event"] == "COMMENT"
    assert payload["comments"][0] == {
        "path": "a.py",
        "line": 42,
        "side": "RIGHT",
        "body": "L42 有风险",
    }
    assert "major" in payload["body"]  # review 概要里带严重度
    assert seen["auth"] == "Bearer t0ken"
    assert result["url"].startswith("https://github.com/")
    assert result["file_path"] == "a.py"


def test_summary_comment_posts_issue_comment() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            201, json={"id": 2, "html_url": "https://github.com/org/app/pull/1#c2"}
        )

    client = make_client(handler)
    result = client.add(
        repo="org/app",
        pr_number=1,
        file_path=None,
        line=None,
        severity="summary",
        body="总体没问题",
    )

    assert seen["url"] == "https://api.github.com/repos/org/app/issues/1/comments"
    assert seen["body"] == {"body": "总体没问题"}
    assert result["url"].endswith("#c2")


def test_inline_422_falls_back_to_issue_comment() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "reviews" in str(request.url):
            return httpx.Response(422, json={"message": "line must be part of the diff"})
        return httpx.Response(
            201, json={"id": 3, "html_url": "https://github.com/org/app/pull/1#c3"}
        )

    client = make_client(handler)
    result = client.add(
        repo="org/app",
        pr_number=1,
        file_path="a.py",
        line=999,
        severity="major",
        body="行号越界的评论",
    )

    assert len(calls) == 2
    assert "reviews" in calls[0]
    assert "/issues/1/comments" in calls[1]  # 降级为汇总评论
    assert result["url"].endswith("#c3")


def test_publish_review_batch() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            201, json={"id": 9, "html_url": "https://github.com/org/app/pull/1#r9"}
        )

    client = make_client(handler)
    result = client.publish_review(
        repo="org/app",
        pr_number=1,
        summary_body="审查报告",
        comments=[
            {"file_path": "a.py", "line": 2, "severity": "major", "body": "问题A"},
            {"file_path": "b.py", "line": 5, "severity": "minor", "body": "问题B"},
        ],
    )

    assert seen["url"].endswith("/pulls/1/reviews")
    assert seen["body"]["body"] == "审查报告"
    assert seen["body"]["event"] == "COMMENT"
    assert len(seen["body"]["comments"]) == 2
    assert seen["body"]["comments"][0]["path"] == "a.py"
    assert result["degraded"] is False


def test_publish_review_422_degrades_to_per_comment() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content)
        calls.append((url, body))
        if url.endswith("/reviews") and len(body.get("comments") or []) > 1:
            return httpx.Response(422, json={"message": "line must be part of the diff"})
        return httpx.Response(201, json={"id": 1, "html_url": "https://x/1"})

    client = make_client(handler)
    result = client.publish_review(
        repo="org/app",
        pr_number=1,
        summary_body="审查报告",
        comments=[
            {"file_path": "a.py", "line": 2, "severity": "major", "body": "问题A"},
            {"file_path": "b.py", "line": 5, "severity": "minor", "body": "问题B"},
        ],
    )

    assert result["degraded"] is True
    assert len(calls) == 4  # 整批 1 次 + 单条 review 2 次 + 汇总 issue comment 1 次
    assert any(url.endswith("/issues/1/comments") for url, _ in calls)


def test_api_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text='{"message": "Resource not accessible"}')

    client = make_client(handler)
    with pytest.raises(RuntimeError, match="403"):
        client.add(
            repo="org/app",
            pr_number=1,
            file_path="a.py",
            line=1,
            severity="minor",
            body="x",
        )
