# pr-sentinel —— AI 代码评审官

PR 提交后，Agent 自动读 diff、查历史、找问题、留评论；每条评论都带证据（代码引用、历史 bug 提交或规范条款），并可用仓库历史里的真实 bug 量化检出率和误报率。

核心差异化：
1. **历史事故库**：审查时检索仓库历史中修过的 bug，判断本次改动是否在重蹈覆辙；
2. **可验证评测**：拿历史"修 bug 的提交"当考卷，检出率 / 误报率是跑出来的数字；
3. **任务系统**：每个 PR 一张工单（Ticket），worker 池并发领取，失败重试、重启可恢复。

## 快速开始（本地，约 5 分钟）

前置：Python 3.11+、[uv](https://docs.astral.sh/uv/)；`.env` 里配置以下四项：

```bash
OPENAI_API_KEY=...          # DeepSeek / 通义等 OpenAI 兼容服务
OPENAI_BASE_URL=https://api.deepseek.com/v1
GITHUB_TOKEN=...            # classic PAT 的 repo 权限即可
GITHUB_WEBHOOK_SECRET=...   # 随便一串长随机数，GitHub 侧用同一个
```

```bash
uv sync
uv run pytest              # 99 个测试
```

## 真实运行指南

**方式一：手动触发（不需要 webhook，适合首次验证）**

```bash
uv run python scripts/trigger_review.py --repo 你的用户名/仓库名 --pr 1   # 窗口 A
uv run python scripts/run_worker.py                                    # 窗口 B
```

worker 会自动 clone 仓库到 `data/repos/`，审查后把评论发到真实 PR。

**方式二：webhook 实时触发（三个窗口，各司其职）**

```bash
# 窗口 1：门房（唯一监听端口的进程）
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 窗口 2：工人（不监听端口，轮询工单库）
uv run python scripts/run_worker.py

# 窗口 3：门铃（把 GitHub 事件转发到本地）
gh extension install cli/gh-webhook   # 只需一次
$secret = (Get-Content .env | Select-String '^GITHUB_WEBHOOK_SECRET=').Line.Split('=',2)[1]
gh webhook forward --repo=你的用户名/仓库名 --events=pull_request --url=http://localhost:8000/webhook --secret=$secret
```

开一个 PR（或对已有 PR 先 Close 再 Reopen），评论会出现在 PR 页面。

**评论形态**：一条汇总 review（风险等级 + 折叠的审查过程）+ 最多 10 条行内评论（按严重度排序、去重、脱敏后）。
**本地留档**：每次运行（包括失败）都会写 `data/traces/{ticket_id}.json`，失败原因可直接回放。

## 排查表

| 现象 | 原因 |
|---|---|
| uvicorn 返回 401 | `GITHUB_WEBHOOK_SECRET` 与 `gh webhook forward --secret` 不一致 |
| worker 报 403 | token 权限不足（classic 需 repo；细粒度需 PR + Issues 写权限） |
| "获取 diff 失败: git diff 退出码 …" | base/head 提交不在本地（检查 fetch）、或 token 无 contents 读权限 |
| 行内评论 422 | 行号不在 diff 内，已自动降级为汇总评论 |
| 评论没出现但工单 done | 模型未发现问题；把改动改成明显 bug 再试 |

## 评测（成绩单）

1. 用 `scripts/ingest_bug_history.py` 采集仓库的修复提交；
2. 按 `evals/datasets/README.md` 的格式攒用例（bug_commit / fix_commit / expected_files）；
3. 跑评测：

```bash
uv run python scripts/run_eval.py --repo /本地仓库路径 --dataset evals/datasets/review_v1.jsonl
```

报告输出到 `evals/reports/`（JSON + Markdown）：文件级检出率、行级命中率、精确率（代理）、误报率（clean 组）、p95 延迟、token 成本。结果带缓存，重跑不重复烧钱。

## Docker 部署

```bash
docker compose up --build        # api（8000 端口）+ worker 双服务
```

- 数据（SQLite、仓库缓存、trace）持久化在 `./data` 挂载卷；
- 部署到公网服务器后，GitHub webhook 直接指向 `https://你的域名/webhook`，不再需要隧道。

## 架构

```
GitHub PR 事件 ──webhook──▶ FastAPI(uvicorn) ──建单──▶ SQLite 工单库
                                                          │ 轮询领取
                                                          ▼
                                              Worker 池（可多实例）
                                                          │
        ┌─────────────────────────────────────────────────┤
        ▼                        ▼                        ▼
   取 diff（git）           Agent 循环                 护栏
        │                 （create_agent 手写版）   脱敏/排序/去重/截断
        ▼                        │                        │
   任务书组装              7 个只读工具               汇总 review +
   （diff+规则）      （read_file / search_code /    行内评论（GitHub API）
                     search_bug_history / …）              │
                                                          ▼
                                              trace 落盘 data/traces/*.json
```

模块：M0 仓库骨架 → M1 工单系统（状态机/原子领取/重试/作废）→ M2 事件接入（验签/幂等）→ M3 diff 解析（真实行号）→ M4 工具层（7 个）→ M5 手写 ReAct 循环（三安全阀）→ M6 上下文+Finding+护栏 → M7 管线+Worker 池 → M8 评测 runner → M9 真 GitHub（隧道/真实评论/自动克隆）。

## 已知限制（MVP 取舍）

- SQLite 单机存储，未做多实例共享（换 Postgres 时 DAO 接口不变）；
- 评测集需要按仓库人工构建 30 条左右；
- ruff 版本差异会影响静态检查的规则集（fail-open 设计，不影响审查主流程）；
- 接入 Langfuse 全链路可观测为可选项，未默认开启。
