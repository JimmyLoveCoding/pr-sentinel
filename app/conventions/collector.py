"""规范库采集：从 CONTRIBUTING.md 和 docs/*.md 里按标题切出"条款"。

每条条款 = 一个标题下的正文段落，附带来源文件与标题——
评论里引用时可以写"违反《CONTRIBUTING.md》『代码风格』一节"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TEXT_LIMIT = 1200


@dataclass
class ConventionSection:
    source: str  # 文件路径（相对仓库根）
    heading: str  # 所在标题
    text: str  # 条款正文


def _collect_file(path: Path, root: Path) -> list[ConventionSection]:
    sections: list[ConventionSection] = []
    heading = "(文档开头)"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            sections.append(
                ConventionSection(
                    source=path.relative_to(root).as_posix(),
                    heading=heading,
                    text=body[:_TEXT_LIMIT],
                )
            )
        buffer = []

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            heading = match.group(2).strip()
        else:
            buffer.append(line)
    flush()
    return sections


def collect_sections(repo_root: Path | str) -> list[ConventionSection]:
    """收集仓库内的规范文档条款。找不到文档时返回空列表。"""
    root = Path(repo_root)
    paths: list[Path] = []

    contributing = root / "CONTRIBUTING.md"
    if contributing.is_file():
        paths.append(contributing)

    docs = root / "docs"
    if docs.is_dir():
        paths.extend(sorted(docs.rglob("*.md"))[:50])

    sections: list[ConventionSection] = []
    for path in paths:
        sections.extend(_collect_file(path, root))
    return sections
