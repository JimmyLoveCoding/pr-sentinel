import json

from app.review.findings import Category, Severity, parse_findings


def item(**overrides) -> dict:
    base = {
        "file": "a.py",
        "line": 42,
        "severity": "blocker",
        "category": "correctness",
        "message": "空指针风险",
        "evidence": "历史提交 a1b2c3d",
        "suggestion": "使用 .get() 兜底",
    }
    base.update(overrides)
    return base


def test_parse_clean_array() -> None:
    findings, errors = parse_findings(json.dumps([item()]))

    assert len(findings) == 1
    assert not errors
    assert findings[0].severity is Severity.BLOCKER
    assert findings[0].category is Category.CORRECTNESS


def test_parse_fenced_json() -> None:
    text = "审查完成：\n```json\n" + json.dumps([item()]) + "\n```\n以上。"
    findings, errors = parse_findings(text)

    assert len(findings) == 1
    assert not errors


def test_parse_prose_around_array() -> None:
    text = "我仔细看了 diff，" + json.dumps([item()]) + " 希望对你有帮助。"
    findings, _ = parse_findings(text)

    assert len(findings) == 1


def test_invalid_items_dropped() -> None:
    text = json.dumps(
        [
            item(),
            item(severity="fatal"),  # 非法严重度
            item(line=0),  # 行号必须 >= 1
            item(file=""),  # 文件不能为空
        ]
    )
    findings, errors = parse_findings(text)

    assert len(findings) == 1
    assert len(errors) == 3


def test_no_json_found() -> None:
    findings, errors = parse_findings("代码看起来不错，没什么问题。")

    assert findings == []
    assert errors


def test_empty_array_means_no_findings() -> None:
    findings, errors = parse_findings("[]")

    assert findings == []
    assert not errors
