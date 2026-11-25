"""审查评论库（mock）：本地方案，代替真实 GitHub 评论。

结构与真实评论对齐（仓库 / PR / 文件 / 行 / 严重度 / 正文），
M9 接 GitHub Review API 时，替换本类为 GitHub 客户端即可。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "review_comments.db"


class CommentSink(Protocol):
    """评论发布接口：本地 mock 库与真实 GitHub 客户端都满足它。

    管线只调用 publish_review：一次提交"汇总报告 + 多条行内评论"。
    """

    def publish_review(
        self,
        *,
        repo: str,
        pr_number: int,
        summary_body: str,
        comments: list[dict],
    ) -> dict: ...

_SCHEMA = """
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    file_path TEXT,
    line INTEGER,
    severity TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
"""


class ReviewCommentStore:
    def __init__(self, db_path: Path | str = _DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS comments ({_SCHEMA})")
        self._conn.commit()

    def add(
        self,
        *,
        repo: str,
        pr_number: int,
        file_path: str | None,
        line: int | None,
        severity: str,
        body: str,
    ) -> dict:
        cur = self._conn.execute(
            "INSERT INTO comments (repo, pr_number, file_path, line, severity, body, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (repo, pr_number, file_path, line, severity, body, datetime.now().isoformat()),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)

    def get(self, comment_id: int) -> dict:
        row = self._conn.execute(
            "SELECT * FROM comments WHERE id = ?", (comment_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_for(self, repo: str, pr_number: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM comments WHERE repo = ? AND pr_number = ? ORDER BY id",
            (repo, pr_number),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def publish_review(
        self,
        *,
        repo: str,
        pr_number: int,
        summary_body: str,
        comments: list[dict],
    ) -> dict:
        """mock 版：汇总报告存一条 summary 评论，行内评论逐条存。"""
        summary = self.add(
            repo=repo,
            pr_number=pr_number,
            file_path=None,
            line=None,
            severity="summary",
            body=summary_body,
        )
        posted = [summary]
        for comment in comments:
            posted.append(
                self.add(
                    repo=repo,
                    pr_number=pr_number,
                    file_path=comment.get("file_path"),
                    line=comment.get("line"),
                    severity=comment.get("severity", "minor"),
                    body=comment["body"],
                )
            )
        return {"summary": summary, "comments": posted}

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM comments").fetchone()["n"]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "repo": row["repo"],
            "pr_number": row["pr_number"],
            "file_path": row["file_path"],
            "line": row["line"],
            "severity": row["severity"],
            "body": row["body"],
            # mock URL：结构像真实评论链接，UI 和测试可以直接使用
            "url": f"mock://{row['repo']}/pull/{row['pr_number']}#comment-{row['id']}",
        }

    def close(self) -> None:
        self._conn.close()
