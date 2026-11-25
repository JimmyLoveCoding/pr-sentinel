import subprocess
from pathlib import Path

from app.github.repo_cache import checkout_commit, ensure_repo


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def make_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q")
    git(origin, "config", "user.email", "t@example.com")
    git(origin, "config", "user.name", "tester")
    (origin / "a.txt").write_text("v1\n", encoding="utf-8")
    git(origin, "add", ".")
    git(origin, "commit", "-qm", "c1")
    return origin


def test_clone_then_fetch(tmp_path) -> None:
    origin = make_origin(tmp_path)
    cache = tmp_path / "cache"

    local = ensure_repo("org/app", cache_dir=cache, remote_url=str(origin))
    assert (local / "a.txt").read_text(encoding="utf-8") == "v1\n"

    (origin / "a.txt").write_text("v2\n", encoding="utf-8")
    git(origin, "add", ".")
    git(origin, "commit", "-qm", "c2")

    ensure_repo("org/app", cache_dir=cache, remote_url=str(origin))
    log = git(local, "log", "--all", "--oneline")
    assert "c2" in log  # 第二次调用执行了 fetch（提交已下载，分支指针在 origin/main 上）


def test_checkout_commit(tmp_path) -> None:
    origin = make_origin(tmp_path)
    cache = tmp_path / "cache"

    local = ensure_repo("org/app", cache_dir=cache, remote_url=str(origin))
    first_sha = git(local, "rev-parse", "HEAD").strip()

    (origin / "a.txt").write_text("v2\n", encoding="utf-8")
    git(origin, "add", ".")
    git(origin, "commit", "-qm", "c2")
    ensure_repo("org/app", cache_dir=cache, remote_url=str(origin))

    checkout_commit(local, first_sha)

    assert (local / "a.txt").read_text(encoding="utf-8") == "v1\n"  # 已切回第一个提交
