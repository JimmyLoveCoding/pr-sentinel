"""评测用例：数据模型与 JSONL 加载。

一条用例对应"历史上的一次 bug 引入提交"，标准答案是"修复提交改动的文件"。
分两层用途：
- layer：问题类型（correctness / security / maintainability / clean）；
- split：dev（调优用）/ test（最终报告用，调 prompt 时不许看）。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str = Field(min_length=1)
    layer: str = Field(pattern="^(correctness|security|maintainability|clean)$")
    split: str = Field(default="dev", pattern="^(dev|test)$")
    repo: str = "org/app"
    pr_number: int = 0
    bug_commit: str = ""  # 被审查的提交：引入 bug 的那次改动
    fix_commit: str = ""  # 修复提交：标准答案的来源
    expected_files: list[str] = Field(default_factory=list)  # 修复提交改动的文件
    expected_lines: dict[str, list[int]] = Field(default_factory=dict)  # 可选的行级答案
    description: str = ""


def load_cases(path: Path | str) -> list[EvalCase]:
    """从 JSONL 文件加载用例；空行忽略，格式不合法直接抛 ValidationError。"""
    cases: list[EvalCase] = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(EvalCase.model_validate_json(line))
    return cases
