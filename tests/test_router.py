from app.agent.router import parse_pr_event, should_handle


def test_review_actions() -> None:
    for action in ("opened", "synchronize", "reopened"):
        assert should_handle(action)


def test_ignored_actions() -> None:
    for action in ("closed", "edited", "labeled", "assigned"):
        assert not should_handle(action)


def test_parse_extracts_base_sha() -> None:
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 7,
            "head": {"sha": "headsha"},
            "base": {"sha": "basesha"},
        },
        "repository": {"full_name": "org/app"},
    }

    decision = parse_pr_event(payload)

    assert decision is not None
    assert decision.head_sha == "headsha"
    assert decision.base_sha == "basesha"
    assert decision.repo == "org/app"


def test_parse_without_base_defaults_empty() -> None:
    payload = {
        "action": "opened",
        "pull_request": {"number": 7, "head": {"sha": "h"}},
        "repository": {"full_name": "org/app"},
    }

    decision = parse_pr_event(payload)

    assert decision is not None
    assert decision.base_sha == ""  # mock 事件没有 base 字段
