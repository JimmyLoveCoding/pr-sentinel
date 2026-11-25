"""仓库本地缓存：按 owner/repo 自动 clone + fetch + checkout。

- 缓存目录默认 data/repos/{owner}__{name}；
- 私有仓库通过 token 克隆（token 拼进 URL，但所有报错信息会做脱敏）；
- 已存在则 fetch 更新；额外尽力抓取 PR 的 head ref（fork 来的 PR 也能取到提交）；
- 审查前必须 checkout 到工单的 head_sha，否则读到的是默认分支的工作区。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "data" / "repos"


def ensure_repo(
    repo: str,
    *,
    pr_number: int | None = None,
    token: str = "",
    cache_dir: Path | str = _DEFAULT_CACHE,
    remote_url: str | None = None,
) -> Path:
    """确保 owner/repo 已在本地缓存，返回本地路径。"""
    owner, name = repo.split("/", 1)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    local = cache / f"{owner}__{name}"

    url = remote_url or f"https://github.com/{repo}.git"
    auth_url = url
    if token and not remote_url:
        auth_url = url.replace("https://", f"https://x-access-token:{token}@")

    if not local.exists():
        _git(["clone", "--quiet", auth_url, str(local)], cwd=cache, secret=token)
    else:
        _git(["fetch", "--quiet", "--prune", "origin"], cwd=local)

    if pr_number is not None:
        try:
            # PR 的 head 提交可能不在任何分支上（来自 fork），单独抓取
            _git(["fetch", "--quiet", "origin", f"pull/{pr_number}/head"], cwd=local)
        except RuntimeError:
            pass  # 本地测试/无 PR ref 时忽略
    return local


def checkout_commit(repo_root: Path | str, sha: str) -> None:
    """把工作区切换到指定提交（审查必须读这个版本的代码）。"""
    _git(["checkout", "--quiet", sha], cwd=Path(repo_root))


def _git(args: list[str], *, cwd: Path, secret: str = "") -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",  # Windows 中文环境下显式 UTF-8，避免 cp936 解码炸裂
        errors="replace",
        timeout=300,
    )
    if result.returncode != 0:
        message = (result.stderr or "").strip()[:300]
        if secret:  # 防止 token 出现在报错信息里
            message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"x-access-token:[^@]+@", "x-access-token:[REDACTED]@", message)
        raise RuntimeError(f"git {args[0]} 失败: {message}")
