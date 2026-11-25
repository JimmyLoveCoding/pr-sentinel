"""历史 bug 提交采集器。

思路：bug 修复提交的 commit message 通常有固定模式
（fix / bug / hotfix / 修复 / closes #123 ...）。
扫描仓库历史，把命中的提交抽出来，连同改动文件和 patch 片段用于入库。

这份数据有两个用途：
- 在线：search_bug_history 工具检索"历史相似事故"；
- 离线：M8 评测的考卷也来自同一批"修复提交"。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_BUG_RE = re.compile(
    r"(?i)\b(fix(es|ed|ing)?|bug|hotfix|repair|resolve[sd]?|close[sd]?)\b|修复|修正|解决"
)

_SNIPPET_LIMIT = 800


@dataclass
class BugCommit:
    sha: str
    committed_at: str  # YYYY-MM-DD
    message: str
    files: list[str]
    snippet: str  # patch 片段，作为"证据"引用


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=60
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def collect_bug_commits(repo_root: Path | str, max_commits: int = 500) -> list[BugCommit]:
    """扫描最近 max_commits 个提交，返回疑似 bug 修复的提交列表。"""
    root = Path(repo_root)
    log = _git(
        root,
        "log",
        f"-n{max_commits}",
        "--date=short",
        "--pretty=format:%H%x09%ad%x09%s",
    )
    if not log:
        return []

    commits: list[BugCommit] = []
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        sha, date, subject = parts
        if not _BUG_RE.search(subject):
            continue

        files_raw = _git(root, "show", "--pretty=format:", "--name-only", sha) or ""
        files = [f.strip() for f in files_raw.splitlines() if f.strip()]
        patch = _git(root, "show", "--pretty=format:", "--unified=0", sha) or ""
        commits.append(
            BugCommit(
                sha=sha,
                committed_at=date,
                message=subject.strip(),
                files=files,
                snippet=patch.strip()[:_SNIPPET_LIMIT],
            )
        )
    return commits
