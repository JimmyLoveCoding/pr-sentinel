"""pr-sentinel API 入口。

M2：POST /webhook —— 收到 PR 事件 → 解析 → 建工单 → 返回 ticket_id。
M9a：验签（配置了 GITHUB_WEBHOOK_SECRET 才启用）+ X-GitHub-Event 过滤。
"""

import json

from fastapi import Depends, FastAPI, HTTPException, Request

from app.agent.router import parse_pr_event
from app.config import Settings, get_settings
from app.github.webhook import is_pr_event, verify_signature
from app.tasks.models import Ticket, TicketKind
from app.tasks.store import TicketStore

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)

_store: TicketStore | None = None


def get_store() -> TicketStore:
    """全局唯一 store；测试用 app.dependency_overrides 换成临时库。"""
    global _store
    if _store is None:
        _store = TicketStore()
    return _store


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@app.post("/webhook")
async def github_webhook(
    request: Request,
    store: TicketStore = Depends(get_store),
    cfg: Settings = Depends(get_settings),
) -> dict:
    body = await request.body()  # 必须用原始字节：验签基于字节，而非解析后的 dict

    if cfg.github_webhook_secret:  # 配置了 secret 才验签；本地 mock 调试跳过
        signature = request.headers.get("X-Hub-Signature-256")
        if not verify_signature(cfg.github_webhook_secret, body, signature):
            raise HTTPException(status_code=401, detail="签名校验失败")

    event = request.headers.get("X-GitHub-Event")
    if not is_pr_event(event):  # ping 等其它事件礼貌回 200，避免 webhook 标红
        return {"status": "ignored", "reason": f"event={event}"}

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"请求体不是合法 JSON: {exc}") from exc

    try:
        decision = parse_pr_event(payload)
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"事件格式错误: 缺少字段 {exc}") from exc

    if decision is None:
        return {"status": "ignored"}

    ticket = store.create(
        Ticket(
            kind=TicketKind.REVIEW_PR,
            repo=decision.repo,
            pr_number=decision.pr_number,
            head_sha=decision.head_sha,
            base_sha=decision.base_sha,
            worker=decision.worker,
            title=f"PR #{decision.pr_number}",
        )
    )
    return {"status": "accepted", "ticket_id": ticket.id}
