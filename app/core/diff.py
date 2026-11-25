"""统一 diff（unified diff）解析器。

输入：git / GitHub API 返回的 patch 文本。
输出：结构化数据 —— 每个文件、每个 hunk、每行的类型与真实行号。

行号的规则（最容易错的地方）：
- 新行号从 hunk 头 "@@ -旧起,旧数 +新起,新数 @@" 里的"新起"开始；
- "+" 行和" "（空格/空行）行会让新行号 +1；
- "-" 行不占新文件的行号，只让旧行号 +1。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")


@dataclass
class DiffLine:
    kind: str  # "added" | "removed" | "context"
    content: str  # 去掉前缀后的正文
    old_line: int | None  # 在旧文件中的行号（added 行为 None）
    new_line: int | None  # 在新文件中的行号（removed 行为 None）


@dataclass
class Hunk:
    old_start: int
    new_start: int
    header: str  # "@@" 行里 @@ 后面的函数上下文，如 " def upload(file):"
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    path: str  # 新文件路径，如 "uploader.py"
    hunks: list[Hunk] = field(default_factory=list)
    is_new: bool = False  # 新建文件
    is_deleted: bool = False  # 删除文件

    @property
    def additions(self) -> int:
        return sum(1 for h in self.hunks for line in h.lines if line.kind == "added")

    @property
    def deletions(self) -> int:
        return sum(1 for h in self.hunks for line in h.lines if line.kind == "removed")

    def added_lines(self) -> list[DiffLine]:
        """所有新增行——审查与行内评论主要关注它们。"""
        return [line for h in self.hunks for line in h.lines if line.kind == "added"]


def parse_diff(text: str) -> list[FileDiff]:
    """解析 unified diff 文本，返回结构化结果。"""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0

    for raw in text.splitlines():
        m = _FILE_RE.match(raw)
        if m:
            current = FileDiff(path=m.group(2))
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue  # diff 头之前的杂项（commit 信息等），跳过

        if raw.startswith("new file mode"):
            current.is_new = True
            continue
        if raw.startswith("deleted file mode"):
            current.is_deleted = True
            continue
        if raw.startswith("--- ") or raw.startswith("+++ ") or raw.startswith("index "):
            continue

        m = _HUNK_RE.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(2))
            hunk = Hunk(old_start=old_no, new_start=new_no, header=raw[m.end() :].strip())
            current.hunks.append(hunk)
            continue

        if hunk is None:
            continue
        if raw.startswith("\\"):  # "\ No newline at end of file"
            continue

        if raw.startswith("+"):
            hunk.lines.append(DiffLine("added", raw[1:], None, new_no))
            new_no += 1
        elif raw.startswith("-"):
            hunk.lines.append(DiffLine("removed", raw[1:], old_no, None))
            old_no += 1
        else:  # 空格开头，或空行（上下文）
            hunk.lines.append(DiffLine("context", raw[1:], old_no, new_no))
            old_no += 1
            new_no += 1

    return files
