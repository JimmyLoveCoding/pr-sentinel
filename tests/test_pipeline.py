import asyncio
import json
import subprocess
from pathlib import Path

from app.llm.client import LLMResponse
from app.review.pipeline import review_ticket
from app.review.store import ReviewCommentStore
from app.tasks.models import Ticket, TicketKind
from app.tools.registry import build_registry


class FakeLLM:
    def __init__(self, scripts: list[LLMResponse]) -> None:
        self.scripts = scripts
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    async def chat(self, messages, *, tools=None, model=None, temperature=0.0):
        self.seen_messages.append(messages)
        script = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        return script


def text_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], usage={"total_tokens": 42})


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args: str) -> None:
        subprocess.run(args, cwd=root, check=True, capture_output=True)

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "tester")

    (root / "uploader.py").write_text("def upload():\n    return None\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "init")

    (root / "uploader.py").write_text(
        "def upload():\n    return {}.get('url')\n", encoding="utf-8"
    )
    run("git", "add", ".")
    run("git", "commit", "-qm", "fix upload")

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return root, sha


def make_ticket(sha: str) -> Ticket:
    return Ticket(
        kind=TicketKind.REVIEW_PR,
        repo="org/app",
        pr_number=128,
        head_sha=sha,
        worker="reviewer",
        title="fix upload",
    )


def make_deps(tmp_path: Path):
    root, sha = make_repo(tmp_path)
    return root, sha, build_registry(root), ReviewCommentStore(tmp_path / "comments.db")


FINDINGS_JSON = json.dumps(
    [
        {
            "file": "uploader.py",
            "line": 2,
            "severity": "major",
            "category": "correctness",
            "message": "缺少判空",
            "evidence": "历史提交 a1b2c3d",
            "suggestion": "加 .get()",
        },
        {
            "file": "uploader.py",
            "line": 2,
            "severity": "fatal",  # 非法严重度：应被 Pydantic 丢弃
            "category": "correctness",
            "message": "坏条目",
        },
    ]
)


def test_pipeline_posts_guarded_comments(tmp_path) -> None:
    root, sha, registry, comment_store = make_deps(tmp_path)
    llm = FakeLLM([text_response(FINDINGS_JSON)])

    outcome = asyncio.run(
        review_ticket(
            make_ticket(sha),
            repo_root=root,
            registry=registry,
            comment_store=comment_store,
            llm=llm,
        )
    )

    assert outcome.ok is True
    assert outcome.posted == 1  # 坏条目被丢弃
    assert outcome.errors  # 丢弃原因有记录
    assert outcome.total_tokens == 42
    assert outcome.trace_path  # trace 已落盘
    from pathlib import Path as _Path

    assert _Path(outcome.trace_path).exists()

    comments = comment_store.list_for("org/app", 128)
    assert len(comments) == 2  # 一条汇总报告 + 一条行内评论
    summary = next(c for c in comments if c["file_path"] is None)
    assert "审查报告" in summary["body"]
    assert "审查过程" in summary["body"]

    inline = next(c for c in comments if c["file_path"])
    assert inline["file_path"] == "uploader.py"
    assert inline["line"] == 2
    assert inline["severity"] == "major"
    assert "证据" in inline["body"]


def test_pipeline_no_findings(tmp_path) -> None:
    root, sha, registry, comment_store = make_deps(tmp_path)
    llm = FakeLLM([text_response("[]")])

    outcome = asyncio.run(
        review_ticket(
            make_ticket(sha),
            repo_root=root,
            registry=registry,
            comment_store=comment_store,
            llm=llm,
        )
    )

    assert outcome.ok is True
    assert outcome.posted == 0
    comments = comment_store.list_for("org/app", 128)
    assert len(comments) == 1  # 只有一条汇总报告（无行内评论）
    assert comments[0]["file_path"] is None
    assert "clean" in comments[0]["body"]


def test_pipeline_agent_loop_detected(tmp_path) -> None:
    root, sha, registry, comment_store = make_deps(tmp_path)
    same_call = LLMResponse(
        content=None,
        tool_calls=[
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "uploader.py"}'},
            }
        ],
        usage={"total_tokens": 5},
    )
    llm = FakeLLM([same_call])

    outcome = asyncio.run(
        review_ticket(
            make_ticket(sha),
            repo_root=root,
            registry=registry,
            comment_store=comment_store,
            llm=llm,
        )
    )

    assert outcome.ok is False
    assert outcome.stopped_reason == "loop_detected"
    assert comment_store.list_for("org/app", 128) == []  # 失败不发布任何评论
    import json
    from pathlib import Path as _Path

    trace = json.loads(_Path(outcome.trace_path).read_text(encoding="utf-8"))
    assert trace["ok"] is False
    assert trace["stopped_reason"] == "loop_detected"
    assert trace["steps"] == 3


def test_pipeline_bad_ref(tmp_path) -> None:
    root, _, registry, comment_store = make_deps(tmp_path)
    llm = FakeLLM([text_response("[]")])

    outcome = asyncio.run(
        review_ticket(
            make_ticket("deadbeefdeadbeef"),
            repo_root=root,
            registry=registry,
            comment_store=comment_store,
            llm=llm,
        )
    )

    assert outcome.ok is False
    assert "获取 diff 失败" in outcome.error


def test_pipeline_prefers_ticket_base_sha(tmp_path) -> None:
    """工单带 base_sha 时，对比范围是 base..head（而不是 head~1..head）。"""
    root = tmp_path / "repo3"
    root.mkdir()

    def run(*args: str) -> str:
        return subprocess.run(
            args, cwd=root, check=True, capture_output=True, text=True
        ).stdout

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "tester")

    (root / "base.py").write_text("x = 1\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "init")
    base_sha = run("git", "rev-parse", "HEAD").strip()

    (root / "filea.py").write_text("A = 1\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "add a")

    (root / "fileb.py").write_text("B = 1\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "add b")
    head_sha = run("git", "rev-parse", "HEAD").strip()

    ticket = Ticket(
        kind=TicketKind.REVIEW_PR,
        repo="org/app",
        pr_number=1,
        head_sha=head_sha,
        base_sha=base_sha,  # 显式基准：diff 应覆盖 filea.py 和 fileb.py
        worker="reviewer",
    )
    llm = FakeLLM([text_response("[]")])

    outcome = asyncio.run(
        review_ticket(
            ticket,
            repo_root=root,
            registry=build_registry(root),
            comment_store=ReviewCommentStore(tmp_path / "c3.db"),
            llm=llm,
        )
    )

    assert outcome.ok is True
    task_text = llm.seen_messages[0][1]["content"]  # user 消息 = 任务书
    assert "filea.py" in task_text  # 若回退 head~1，就看不到 filea.py
    assert "fileb.py" in task_text
