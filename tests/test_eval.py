import asyncio
import json
import subprocess
from pathlib import Path

from app.evaluation.cases import EvalCase, load_cases
from app.evaluation.runner import CaseResult, aggregate, evaluate
from app.llm.client import LLMResponse
from app.tools.registry import build_registry


class FakeLLM:
    def __init__(self, scripts: list[LLMResponse]) -> None:
        self.scripts = scripts
        self.calls = 0

    async def chat(self, messages, *, tools=None, model=None, temperature=0.0):
        script = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        return script


def text_response(content: str, tokens: int = 10) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], usage={"total_tokens": tokens})


FINDINGS_JSON = json.dumps(
    [
        {
            "file": "uploader.py",
            "line": 2,
            "severity": "major",
            "category": "correctness",
            "message": "未判空",
            "evidence": "历史提交 a1b2c3d",
        }
    ]
)


def make_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """三个提交：init → 引入 bug → 修复。返回 (root, bug_sha, fix_sha)。"""
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args: str) -> str:
        return subprocess.run(
            args, cwd=root, check=True, capture_output=True, text=True
        ).stdout

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "tester")

    (root / "uploader.py").write_text("def upload():\n    return None\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-qm", "init")
    run("git", "rev-parse", "HEAD")

    (root / "uploader.py").write_text(
        "def upload():\n    return resp['url']\n", encoding="utf-8"
    )
    run("git", "add", ".")
    run("git", "commit", "-qm", "refactor upload")
    bug_sha = run("git", "rev-parse", "HEAD").strip()

    (root / "uploader.py").write_text(
        "def upload():\n    return (resp or {}).get('url')\n", encoding="utf-8"
    )
    run("git", "add", ".")
    run("git", "commit", "-qm", "fix upload")
    fix_sha = run("git", "rev-parse", "HEAD").strip()
    return root, bug_sha, fix_sha


def make_cases(bug_sha: str, fix_sha: str) -> list[EvalCase]:
    return [
        EvalCase(
            id="case-bug",
            layer="correctness",
            split="dev",
            repo="org/app",
            pr_number=1,
            bug_commit=bug_sha,
            fix_commit=fix_sha,
            expected_files=["uploader.py"],
            expected_lines={"uploader.py": [2]},
            description="upload 未判空",
        ),
        EvalCase(
            id="case-clean",
            layer="clean",
            split="dev",
            repo="org/app",
            pr_number=2,
            bug_commit=bug_sha,
            fix_commit=fix_sha,
            description="同一改动按 clean 组测误报",
        ),
    ]


def test_load_cases(tmp_path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps({"id": "a", "layer": "correctness", "bug_commit": "sha1"}) + "\n\n"
        + json.dumps({"id": "b", "layer": "clean", "bug_commit": "sha2"}) + "\n",
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert [c.id for c in cases] == ["a", "b"]
    assert cases[0].split == "dev"  # 默认值生效


def test_aggregate_metrics() -> None:
    results = [
        CaseResult(case_id="a", layer="correctness", hit=True, line_hit=True,
                   posted=2, matched=1, latency_s=1.0, tokens=100),
        CaseResult(case_id="b", layer="clean", hit=False, posted=1,
                   latency_s=2.0, tokens=50),
    ]

    report = aggregate(results)
    m = report["metrics"]

    assert m["file_hit_rate"] == 1.0
    assert m["line_hit_rate"] == 1.0
    assert m["precision_proxy"] == round(1 / 3, 4)
    assert m["false_positive_rate"] == 1.0
    assert m["total_tokens"] == 150


def test_evaluate_end_to_end(tmp_path) -> None:
    root, bug_sha, fix_sha = make_repo(tmp_path)
    cases = make_cases(bug_sha, fix_sha)
    llm = FakeLLM([text_response(FINDINGS_JSON), text_response("[]")])
    out_dir = tmp_path / "reports"

    report = asyncio.run(
        evaluate(
            cases,
            repo_root=root,
            registry=build_registry(root),
            llm=llm,
            out_dir=out_dir,
        )
    )

    m = report["metrics"]
    assert m["file_hit_rate"] == 1.0  # 命中预期文件
    assert m["line_hit_rate"] == 1.0  # 行号 2 在 ±5 内
    assert m["precision_proxy"] == 1.0
    assert m["false_positive_rate"] == 0.0  # clean 用例零评论
    assert report["by_layer"]["correctness"]["cases"] == 1
    assert list(out_dir.glob("report-*.json"))
    assert list(out_dir.glob("report-*.md"))

    # 第二次运行：命中缓存，不再调用模型
    calls_before = llm.calls
    asyncio.run(
        evaluate(
            cases,
            repo_root=root,
            registry=build_registry(root),
            llm=llm,
            out_dir=out_dir,
        )
    )
    assert llm.calls == calls_before == 2


def test_clean_case_false_positive(tmp_path) -> None:
    root, bug_sha, fix_sha = make_repo(tmp_path)
    clean_case = EvalCase(
        id="case-clean-fp",
        layer="clean",
        bug_commit=bug_sha,
        fix_commit=fix_sha,
    )
    llm = FakeLLM([text_response(FINDINGS_JSON)])  # 对 clean 用例也报了问题

    report = asyncio.run(
        evaluate(
            [clean_case],
            repo_root=root,
            registry=build_registry(root),
            llm=llm,
            out_dir=tmp_path / "reports",
        )
    )

    assert report["metrics"]["false_positive_rate"] == 1.0
    assert report["cases"][0]["hit"] is False
