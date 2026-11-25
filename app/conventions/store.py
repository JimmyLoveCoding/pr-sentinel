"""规范库（SQLite）：条款入库与关键词检索。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.conventions.collector import ConventionSection, collect_sections
from app.core.text import terms as _terms

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "conventions.db"

_SCHEMA = """
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    heading TEXT NOT NULL,
    text TEXT NOT NULL,
    search_text TEXT NOT NULL
"""


class ConventionStore:
    def __init__(self, db_path: Path | str = _DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS conventions ({_SCHEMA})")
        self._conn.commit()

    def replace_all(self, sections: list[ConventionSection]) -> int:
        """整体替换（文档更新后重新摄入，不会产生重复条款）。"""
        self._conn.execute("DELETE FROM conventions")
        for section in sections:
            search_text = f"{section.heading} {section.text}".lower()
            self._conn.execute(
                "INSERT INTO conventions (source, heading, text, search_text)"
                " VALUES (?, ?, ?, ?)",
                (section.source, section.heading, section.text, search_text),
            )
        self._conn.commit()
        return len(sections)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        terms = _terms(query)
        if not terms:
            return []

        where = " OR ".join("search_text LIKE ?" for _ in terms)
        rows = self._conn.execute(
            f"SELECT * FROM conventions WHERE {where}",
            tuple(f"%{t}%" for t in terms),
        ).fetchall()

        scored = []
        for row in rows:
            score = sum(1 for t in terms if t in row["search_text"])
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)

        return [
            {
                "source": row["source"],
                "heading": row["heading"],
                "text": row["text"][:300],
                "score": score,
            }
            for score, row in scored[:top_k]
        ]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM conventions").fetchone()["n"]

    def close(self) -> None:
        self._conn.close()


def ingest_repo(repo_root: Path | str, store: ConventionStore) -> int:
    return store.replace_all(collect_sections(repo_root))
