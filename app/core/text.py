"""检索用的轻量文本工具（bug 库与规范库共用）。"""

from __future__ import annotations

import re

_TERM_RE = re.compile(r"[a-z0-9_#]+|[一-鿿]{2,}")


def terms(query: str) -> list[str]:
    """拆检索词：英文按单词、中文按 2 字以上连续片段；去重保序。"""
    return list(dict.fromkeys(_TERM_RE.findall(query.lower())))
