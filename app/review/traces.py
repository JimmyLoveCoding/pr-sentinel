"""审查 trace 落盘：每次运行（含失败）写一份 JSON。

为什么 GitHub 评论之外还要本地留档：
- 失败的运行根本没有评论可看，但最需要排查；
- 评论是给人看的文本，trace 是给程序用的结构化数据（评测、聚合、回放）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

TRACE_DIR = Path(__file__).resolve().parents[2] / "data" / "traces"


def save_trace(
    ticket_id: str,
    *,
    trace: list[dict],
    ok: bool,
    steps: int = 0,
    total_tokens: int = 0,
    stopped_reason: str = "final",
    posted: int = 0,
    error: str = "",
    elapsed_s: float = 0.0,
) -> str:
    """写入 data/traces/{ticket_id}.json，返回文件路径。写入失败不影响主流程。"""
    payload = {
        "ticket_id": ticket_id,
        "saved_at": datetime.now().isoformat(),
        "ok": ok,
        "stopped_reason": stopped_reason,
        "steps": steps,
        "total_tokens": total_tokens,
        "posted": posted,
        "error": error,
        "elapsed_s": round(elapsed_s, 3),
        "trace": trace,
    }
    try:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACE_DIR / f"{ticket_id}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(path)
    except OSError:
        return ""
