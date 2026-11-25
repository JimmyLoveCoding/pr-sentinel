"""GitHub webhook 校验：验签与事件过滤。

验签原理：GitHub 用 webhook secret 对请求体做 HMAC-SHA256，
把结果放在 X-Hub-Signature-256 头（形如 "sha256=<hex>"）。
我们用同样的 secret 对收到的**原始字节**重算一遍，一致才放行。

注意：必须用原始字节——JSON 解析后再序列化，字节就变了，签名必然对不上。
"""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """校验 X-Hub-Signature-256 是否与请求体匹配。"""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    # compare_digest 是防时序攻击的常数时间比较
    return hmac.compare_digest(f"sha256={expected}", signature)


def is_pr_event(event_header: str | None) -> bool:
    """X-GitHub-Event 是否为 pull_request。

    没有该头（本地 mock 调试）时视为 PR 事件，放行。
    """
    if event_header is None:
        return True
    return event_header == "pull_request"
