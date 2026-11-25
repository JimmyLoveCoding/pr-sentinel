"""list_changed_files 工具：返回 PR 改动的文件清单与增删统计。

实现：在本地克隆仓库里跑 `git diff --numstat base head`。
在本地跑而不是调 GitHub API：快、省 API 配额，且和 read_file 共用同一个仓库副本。
将来接真 GitHub 时可换成 /pulls/{n}/files，工具签名不变。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.tools.base import Tool


def make_list_changed_files_tool(repo_root: Path) -> Tool:
    async def list_changed_files(base: str, head: str) -> dict:
        result = subprocess.run(
            ["git", "diff", "--numstat", base, head],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {"error": f"git diff 失败: {result.stderr.strip()[:300]}"}

        files = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            files.append(
                {
                    "path": path,
                    "additions": int(added) if added.isdigit() else 0,
                    "deletions": int(deleted) if deleted.isdigit() else 0,
                }
            )
        return {"count": len(files), "files": files, "base": base, "head": head}

    return Tool(
        name="list_changed_files",
        description=(
            "列出本次 PR 改动的所有文件及每个文件的新增/删除行数。"
            "审查开始时先用它了解改动范围，决定审查顺序和重点。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "base": {
                    "type": "string",
                    "description": "对比基准的 git ref，如 'main' 或基准分支的 commit SHA",
                },
                "head": {
                    "type": "string",
                    "description": "目标提交的 git ref，通常是 PR 的 head_sha",
                },
            },
            "required": ["base", "head"],
        },
        fn=list_changed_files,
    )
