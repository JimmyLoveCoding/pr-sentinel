"""工具注册表工厂。

基础四件套：read_file / search_code / list_changed_files / run_linters
可选：search_bug_history（bug_store）/ search_conventions（conv_store）/
      post_review_comment（comment_store + repo + pr_number）
"""

from pathlib import Path

from app.bughistory.store import BugHistoryStore
from app.conventions.store import ConventionStore
from app.review.store import ReviewCommentStore
from app.tools.base import ToolRegistry
from app.tools.bug_history import make_search_bug_history_tool
from app.tools.conventions import make_search_conventions_tool
from app.tools.linters import make_run_linters_tool
from app.tools.list_changed_files import make_list_changed_files_tool
from app.tools.post_comment import make_post_review_comment_tool
from app.tools.read_file import make_read_file_tool
from app.tools.repo_source import LocalRepoSource
from app.tools.search_code import make_search_code_tool


def build_registry(
    repo_root: Path,
    *,
    bug_store: BugHistoryStore | None = None,
    conv_store: ConventionStore | None = None,
    comment_store: ReviewCommentStore | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
) -> ToolRegistry:
    source = LocalRepoSource(repo_root)
    registry = ToolRegistry()
    registry.register(make_read_file_tool(source))
    registry.register(make_search_code_tool(source))
    registry.register(make_list_changed_files_tool(repo_root))
    registry.register(make_run_linters_tool(repo_root))
    if bug_store is not None:
        registry.register(make_search_bug_history_tool(bug_store))
    if conv_store is not None:
        registry.register(make_search_conventions_tool(conv_store))
    if comment_store is not None and repo is not None and pr_number is not None:
        registry.register(make_post_review_comment_tool(comment_store, repo, pr_number))
    return registry
