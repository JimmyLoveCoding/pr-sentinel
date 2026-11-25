from app.review.findings import Category, Finding, Severity
from app.review.summary import build_summary_body, risk_level


def make(severity: Severity = Severity.MINOR) -> Finding:
    return Finding(
        file="a.py",
        line=1,
        severity=severity,
        category=Category.CORRECTNESS,
        message="问题",
    )


def test_risk_level() -> None:
    assert risk_level([]) == "clean"
    assert risk_level([make(Severity.MINOR)]) == "minor"
    assert risk_level([make(Severity.MINOR), make(Severity.MAJOR)]) == "major"
    assert risk_level([make(Severity.BLOCKER), make(Severity.MAJOR)]) == "blocker"


def test_clean_summary_has_fold() -> None:
    body = build_summary_body(
        [], trace=[], steps=0, total_tokens=0, elapsed_s=0.0
    )

    assert "clean" in body
    assert "<details>" in body
    assert "审查过程" in body


def test_summary_counts_and_trace_lines() -> None:
    trace = [
        {
            "step": 1,
            "tool_calls": [{"name": "read_file", "args": '{"path": "a.py"}'}],
            "usage": {},
        },
        {"step": 2, "tool_calls": [], "usage": {}},
    ]
    body = build_summary_body(
        [make(Severity.MAJOR)],
        trace=trace,
        steps=2,
        total_tokens=100,
        elapsed_s=3.2,
    )

    assert "major" in body
    assert "发现 1 个问题" in body
    assert "major × 1" in body
    assert "`read_file`" in body  # 工具名进了折叠块
    assert "无工具调用" in body  # 纯回复步也有一条记录
    assert "</details>" in body
