# 评测数据集格式（JSONL，一行一条用例）

```json
{"id": "case-001", "layer": "correctness", "split": "dev", "repo": "org/app", "pr_number": 42,
 "bug_commit": "<引入 bug 的提交 SHA>", "fix_commit": "<后来修复它的提交 SHA>",
 "expected_files": ["uploader.py"], "expected_lines": {"uploader.py": [42]},
 "description": "upload 未对返回值判空"}
```

## 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| id | ✅ | 用例唯一标识 |
| layer | ✅ | correctness / security / maintainability / clean（clean = 期望零评论） |
| split | | dev（调优用）/ test（最终报告用） |
| repo / pr_number | | 仓库名与伪 PR 号（仅用于评论归属） |
| bug_commit | ✅ | 被审查的提交：审查对象是 `bug_commit~1..bug_commit` 的 diff |
| fix_commit | | 修复提交（用于人工核对答案来源） |
| expected_files | ✅（clean 除外） | 标准答案：修复提交改动的文件 |
| expected_lines | | 可选行级答案：文件 → 行号列表（命中容差 ±5 行） |
| description | | 用例说明 |

## 如何构建 30 条

1. 跑 `scripts/ingest_bug_history.py` 采集本仓库的修复提交；
2. 对每个修复提交，在 `git log` 里找到它修复的"引入提交"（通常可用 `git log --follow` + blame 辅助定位；MVP 允许人工挑选）；
3. 填入用例：`bug_commit` = 引入提交，`fix_commit` = 修复提交，
   `expected_files` = 修复提交改动的文件；
4. 分层建议：correctness 8 条、security 8 条、maintainability 8 条、clean 6 条；
   split 建议 20 dev / 10 test（test 只在出最终报告时用）。

> 注意：clean 用例挑"普通重构/文档类提交"，它们包含了改动但没有已知 bug，
> 用来测误报率——这是最能暴露"AI 乱报"的一组。
