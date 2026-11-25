from app.review.findings import Category, Finding, Severity
from app.review.guardrails import apply_guardrails, redact_text


def make(
    file: str = "a.py",
    line: int = 1,
    severity: Severity = Severity.MINOR,
    category: Category = Category.CORRECTNESS,
    message: str = "问题",
    evidence: str = "",
    suggestion: str = "",
) -> Finding:
    return Finding(
        file=file,
        line=line,
        severity=severity,
        category=category,
        message=message,
        evidence=evidence,
        suggestion=suggestion,
    )


def test_redact_common_secrets() -> None:
    assert "sk-" not in redact_text("发现 key sk-abcdef123456789 泄露")
    assert "AKIAABCDEFGHIJKLMNOP" not in redact_text("AKIAABCDEFGHIJKLMNOP 在里面")
    assert "hunter2" not in redact_text("password=hunter2 被硬编码")
    assert "[REDACTED]" in redact_text("sk-abcdef123456789")


def test_sort_by_severity() -> None:
    findings = [
        make(line=1, severity=Severity.MINOR),
        make(line=2, severity=Severity.BLOCKER),
        make(line=3, severity=Severity.MAJOR),
    ]

    result = apply_guardrails(findings)

    assert [f.severity for f in result] == [
        Severity.BLOCKER,
        Severity.MAJOR,
        Severity.MINOR,
    ]


def test_dedupe_keeps_most_severe() -> None:
    findings = [
        make(line=42, severity=Severity.MAJOR, message="问题 A"),
        make(line=42, severity=Severity.BLOCKER, message="问题 B"),  # 同位置同类，更严重
        make(line=42, severity=Severity.MINOR, category=Category.SECURITY),  # 不同类别，保留
    ]

    result = apply_guardrails(findings)

    assert len(result) == 2
    assert result[0].severity is Severity.BLOCKER  # 同 key 保留了最严重的一条


def test_truncate_to_max_count() -> None:
    findings = [make(line=i) for i in range(1, 13)]

    result = apply_guardrails(findings, max_count=10)

    assert len(result) == 10


def test_redaction_applies_to_all_text_fields() -> None:
    findings = [
        make(
            message="token=abc123",
            evidence="sk-abcdef123456789",
            suggestion="改成 password=xyz 方式",
        )
    ]

    result = apply_guardrails(findings)

    assert "[REDACTED]" in result[0].message
    assert "[REDACTED]" in result[0].evidence
    assert "[REDACTED]" in result[0].suggestion
