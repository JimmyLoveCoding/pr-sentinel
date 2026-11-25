"""审查发现的护栏：脱敏 → 排序 → 去重 → 截断。

为什么护栏必须在模型之外执行：如果模型自己发评论，它就能绕过"最多 N 条、
先脱敏、先去重"这些规则。让模型只产出数据、由确定性代码做最后的把关，
规则才真正"管得住"。

顺序有讲究：
1. 先脱敏——脏数据不进任何后续环节（日志、存储、展示）；
2. 再排序——严重度高的排前面，后面截断时先保命；
3. 再去重——排完序后同一位置保留的自然是严重度最高的一条；
4. 最后截断——单 PR 最多 N 条，防评论刷屏。
"""

from __future__ import annotations

import re

from app.review.findings import Finding, Severity

_SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.MAJOR: 1, Severity.MINOR: 2}

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),                 # API key 形态
    re.compile(r"AKIA[0-9A-Z]{16}"),                     # AWS Access Key
    re.compile(r"(?i)(password|passwd|secret|token)\s*[=:]\s*\S+"),  # password=xxx
)

_REDACTED = "[REDACTED]"


def redact_text(text: str) -> str:
    """把疑似密钥/口令替换为 [REDACTED]。"""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def apply_guardrails(findings: list[Finding], max_count: int = 10) -> list[Finding]:
    """对发现列表执行四道护栏，返回最终可发布的列表。"""
    # 1) 脱敏：三个自由文本字段
    cleaned = [
        f.model_copy(
            update={
                "message": redact_text(f.message),
                "evidence": redact_text(f.evidence),
                "suggestion": redact_text(f.suggestion),
            }
        )
        for f in findings
    ]

    # 2) 排序：严重度 → 文件名 → 行号（稳定、可复现）
    cleaned.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.file, f.line))

    # 3) 去重：(文件, 行号, 类别) 视为同一问题，保留排序后的第一条（最严重）
    seen: set[tuple[str, int, str]] = set()
    unique: list[Finding] = []
    for finding in cleaned:
        key = (finding.file, finding.line, finding.category.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)

    # 4) 截断
    return unique[:max_count]
