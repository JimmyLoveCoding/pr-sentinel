"""仓库读取器：工具的"数据源"抽象。

审查工具永远通过这一层读代码，不直接碰 GitHub API。
现在只有本地目录实现（指向克隆下来的仓库）；将来接 GitHub 时新增一个
GitHubRepoSource，工具代码不用改。

安全约定：所有路径必须落在仓库根目录之内（防目录穿越）。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class RepoSource:
    def read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> dict:
        raise NotImplementedError

    def search_code(
        self, query: str, glob: str | None = None, max_results: int = 20
    ) -> dict:
        raise NotImplementedError


class LocalRepoSource(RepoSource):
    """指向本地克隆目录的读取器。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"仓库目录不存在: {self.root}")

    def _safe_path(self, path: str) -> Path:
        """把相对路径解析到仓库内；越界（../ 之类）直接拒绝。"""
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            raise ValueError(f"路径越界: {path}")
        return full

    def read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> dict:
        try:
            full = self._safe_path(path)
        except ValueError as exc:
            return {"error": str(exc)}
        if not full.is_file():
            return {"error": f"文件不存在: {path}"}

        content = full.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total = len(lines)

        if start_line is not None or end_line is not None:
            start = max(1, start_line or 1)
            end = min(total, end_line or total)
            if start > end:
                return {"error": f"行范围无效: {start}-{end}（文件共 {total} 行）"}
            lines = lines[start - 1 : end]
            return {
                "path": path,
                "start_line": start,
                "end_line": end,
                "total_lines": total,
                "content": "\n".join(lines),
            }

        # 全文件：超过 200KB 截断，避免撑爆上下文
        truncated = len(content) > 200_000
        if truncated:
            content = content[:200_000]
        return {
            "path": path,
            "total_lines": total,
            "truncated": truncated,
            "content": content,
        }

    def search_code(
        self, query: str, glob: str | None = None, max_results: int = 20
    ) -> dict:
        """在仓库内搜索字符串/符号，返回匹配的文件、行号、代码行。

        优先用 ripgrep（快、自带 .gitignore 过滤）；环境里没有 rg 时降级为纯 Python 遍历。
        """
        matches = self._search_with_rg(query, glob, max_results)
        if matches is None:
            matches = self._search_with_python(query, glob, max_results)
        return {
            "query": query,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
            "matches": matches,
        }

    def _search_with_rg(
        self, query: str, glob: str | None, max_results: int
    ) -> list[dict] | None:
        """调用 ripgrep；rg 不存在或异常时返回 None，交给 Python 降级实现。"""
        args = ["rg", "--line-number", "--no-heading", "--color", "never"]
        if glob:
            args += ["--glob", glob]
        args += ["--", query, "."]
        try:
            result = subprocess.run(
                args, cwd=self.root, capture_output=True, text=True, timeout=30
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode not in (0, 1):  # 1 = 没有匹配
            return None

        matches: list[dict] = []
        for line in result.stdout.splitlines():
            m = re.match(r"^\./(.+?):(\d+):(.*)$", line)
            if not m:
                continue
            matches.append(
                {"file": m.group(1), "line": int(m.group(2)), "text": m.group(3)}
            )
            if len(matches) >= max_results:
                break
        return matches

    def _search_with_python(
        self, query: str, glob: str | None, max_results: int
    ) -> list[dict]:
        pattern = re.compile(re.escape(query))
        matches: list[dict] = []
        for path in sorted(self.root.rglob("*")):
            if len(matches) >= max_results:
                break
            if not path.is_file() or ".git" in path.parts:
                continue
            if glob and not path.match(glob):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    rel = path.relative_to(self.root).as_posix()
                    matches.append({"file": rel, "line": i, "text": line.strip()})
                    if len(matches) >= max_results:
                        break
        return matches
