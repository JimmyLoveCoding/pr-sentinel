from app.agent.context import build_review_task


def test_task_contains_key_parts() -> None:
    task = build_review_task(
        repo="org/app",
        pr_number=128,
        title="fix: uploader retry",
        head_sha="abc123",
        diff_text="@@ -40,2 +40,3 @@\n-    return resp.json()['url']\n+    return resp.json().get('url')",
    )

    assert "org/app" in task
    assert "#128" in task
    assert "fix: uploader retry" in task
    assert "abc123" in task
    assert "resp.json().get('url')" in task
    assert "JSON 数组" in task  # 输出格式要求
    assert "severity" in task
    assert "search_bug_history" in task  # 指引模型去用历史库


def test_large_diff_truncated_with_note() -> None:
    task = build_review_task(
        repo="org/app",
        pr_number=1,
        title="big",
        head_sha="sha",
        diff_text="x" * 500,
        max_diff_chars=100,
    )

    assert "diff 已截断" in task
    assert task.count("x") <= 200  # 原文只保留前 100 字符左右
