"""run_linters 工具：对指定文件跑 ruff，返回结构化告警。

定位：给 LLM 提供线索，不是必须通过的关卡。

三条约定：
- 只做文件级、无依赖的检查（ruff 单文件可跑，不需要项目能构建）；
- fail-open：ruff 不存在 / 超时 / 报错 → 返回空结果 + 说明，审查继续；
- 路径必须落在仓库内（复用仓库边界的思路）。
"""

from __future__ import annotations

import json
import shutil
import subprocess#这个就是ruff的调用，ruff是一个python的linter工具，主要用于检查代码风格和潜在的错误。
from pathlib import Path

from app.tools.base import Tool

_MAX_FILES = 20


def make_run_linters_tool(repo_root: Path) -> Tool:
    root = Path(repo_root).resolve()

    async def run_linters(files: list[str]) -> dict:
        if not files:
            return {"error": "files 不能为空"}

        safe_files: list[str] = []
        for rel in files[:_MAX_FILES]:
            full = (root / rel).resolve()
            if not full.is_relative_to(root) or not full.is_file():
                return {"error": f"非法或不存在文件: {rel}"}
            safe_files.append(rel)

        if shutil.which("ruff") is None:
            return {"findings": [], "note": "linters_unavailable: 未安装 ruff"}

        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format", "json", "--no-cache", "--", *safe_files],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {"findings": [], "note": "linters_unavailable: ruff 超时"}

        if result.returncode not in (0, 1):  # 1 = 有告警
            return {
                "findings": [],
                "note": f"linters_unavailable: ruff 退出码 {result.returncode}",
            }

        try:
            raw = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return {"findings": [], "note": "linters_unavailable: 输出无法解析"}

        def _rel(filename: str | None) -> str | None:
            """把 ruff 返回的路径归一化为相对仓库根的路径（不同版本行为不一）。"""
            if not filename:
                return filename
            try:
                return Path(filename).resolve().relative_to(root).as_posix()
            except ValueError:
                return filename

        findings = [
            {
                "tool": "ruff",
                "rule_id": item.get("code"),
                "file": _rel(item.get("filename")),
                "line": (item.get("location") or {}).get("row"),
                "severity": item.get("severity"),  # 新版本 ruff 提供；旧版本为 None
                "message": item.get("message"),
            }
            for item in raw
        ]
        return {"count": len(findings), "findings": findings}

    return Tool(
        name="run_linters",
        description=(
            "对指定文件运行 ruff 静态检查（语法级、无需项目依赖）并返回结构化告警。"
            "告警只是线索：需要结合上下文判断是否真的有问题、严重程度如何。"
            "文件路径使用相对仓库根目录的路径。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要检查的文件相对路径列表（最多 20 个，通常取自 diff 的改动文件）",
                },
            },
            "required": ["files"],
        },
        fn=run_linters,
    )
