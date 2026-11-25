"""历史 bug 库（SQLite）。

MVP 的检索方式是"关键词命中计数"：把查询拆成词，看每条记录命中几个词，
命中越多分越高，同分按时间新者优先。简单、确定、可测试。

升级路径：将来换成 embedding 向量检索，只替换 search() 的内部实现，
工具签名与返回格式保持不变。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.bughistory.collector import BugCommit, collect_bug_commits
from app.core.text import terms as _terms

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "bug_history.db"

_SCHEMA = """
    sha TEXT PRIMARY KEY,
    committed_at TEXT NOT NULL,
    message TEXT NOT NULL,
    files TEXT NOT NULL,
    snippet TEXT NOT NULL,
    search_text TEXT NOT NULL
"""


class BugHistoryStore:
    def __init__(self, db_path: Path | str = _DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS bug_commits ({_SCHEMA})")
        self._conn.commit()

    def add_many(self, commits: list[BugCommit]) -> int:
        """批量入库；同一 sha 重复入库会覆盖（幂等）。返回入库条数。"""
        for commit in commits:
            search_text = " ".join(
                [commit.message.lower(), *[f.lower() for f in commit.files], commit.snippet.lower()]
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO bug_commits"
                " (sha, committed_at, message, files, snippet, search_text)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    commit.sha,
                    commit.committed_at,
                    commit.message,
                    json.dumps(commit.files, ensure_ascii=False),
                    commit.snippet,
                    search_text,
                ),
            )
        self._conn.commit()
        return len(commits)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        terms = _terms(query)
        if not terms:
            return []

        where = " OR ".join("search_text LIKE ?" for _ in terms)
        rows = self._conn.execute(
            f"SELECT * FROM bug_commits WHERE {where}",
            tuple(f"%{t}%" for t in terms),
        ).fetchall()

        scored = []
        for row in rows:
            score = sum(1 for t in terms if t in row["search_text"])
            scored.append((score, row["committed_at"], row))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

        return [
            {
                "sha": row["sha"][:12],
                "date": row["committed_at"],
                "message": row["message"],
                "files": json.loads(row["files"]),
                "snippet": row["snippet"][:400],
                "score": score,
            }
            for score, _, row in scored[:top_k]
        ]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM bug_commits").fetchone()["n"]

    def close(self) -> None:
        self._conn.close()


def ingest_repo(
    repo_root: Path | str, store: BugHistoryStore, max_commits: int = 500
) -> int:
    """采集仓库历史中的 bug 修复提交并入库。"""
    return store.add_many(collect_bug_commits(repo_root, max_commits=max_commits))
