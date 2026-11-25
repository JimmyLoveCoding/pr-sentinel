"""Worker 规格（M1 / M7 完善）。

每个 Worker = 独立的执行循环 + 自己的工具子集与提示词。
当前只定义 reviewer 一种 Worker；日报/汇总类 Worker 留到 M9。
"""

from dataclasses import dataclass


@dataclass(frozen=True)#这个frozen=True参数表示这个数据类是不可变的，一旦创建实例后，其属性值不能被修改。
class WorkerSpec:
    name: str
    system_prompt: str
    tool_names: tuple[str, ...]


WORKER_SPECS: dict[str, WorkerSpec] = {
    # 审查员是只读岗位：工具清单里没有任何写操作。
    # 评论发布由管线在"解析 Finding → 护栏"之后统一执行（M7），
    # 这样护栏（去重/截断/脱敏）在模型控制之外，无法被绕过。
    "reviewer": WorkerSpec(
        name="reviewer",
        system_prompt="你是代码评审员。只依据提供的 diff 和工具检索结果给出有证据的审查意见，不臆测。",
        tool_names=(
            "list_changed_files",
            "read_file",
            "search_code",
            "search_bug_history",
            "search_conventions",
            "run_linters",
        ),
    ),
}
