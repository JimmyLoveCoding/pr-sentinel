"""git 命令薄封装：供管线取 diff 用。

只做一件事：跑 `git diff base head` 返回原始 patch 文本。
失败时抛 RuntimeError 并带上 git 的原始报错（否则排障时无从下手）。

Windows 兼容性：
- 显式用 UTF-8 解码输出（中文 Windows 默认 cp936，读 UTF-8 内容会炸）；
- --no-ext-diff：屏蔽用户全局配置里的外部 diff 工具干扰。
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_diff_text(repo_root: Path | str, base: str, head: str) -> str | None:
    """返回 base..head 的统一 diff 文本。

    - 仓库不存在 / git 不存在 / 超时：返回 None；
    - git 执行失败（ref 无效等）：抛 RuntimeError，消息里带 stderr。
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--no-color", "--no-ext-diff", base, head],
            cwd=Path(repo_root),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:300]
        raise RuntimeError(f"git diff 退出码 {result.returncode}: {stderr}")
    return result.stdout
