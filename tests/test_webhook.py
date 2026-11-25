import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_store
from app.tasks.models import TicketStatus
from app.tasks.store import TicketStore


@pytest.fixture
def client(tmp_path):
    """每个测试一个全新的临时数据库 + 显式清空 secret（隔离真实 .env）。"""
    store = TicketStore(tmp_path / "tickets.db")
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(github_webhook_secret="")
    yield TestClient(app), store
    app.dependency_overrides.clear()
    store.close()


@pytest.fixture
def secured_client(tmp_path):
    """启用验签的客户端：配置了 webhook secret。"""
    store = TicketStore(tmp_path / "tickets.db")
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(
        github_webhook_secret="s3cret"
    )
    yield TestClient(app), store
    app.dependency_overrides.clear()
    store.close()


def make_payload(
    action: str = "opened",
    pr_number: int = 128,
    sha: str = "abc123",
    base: str = "base123",
) -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": pr_number,
            "head": {"sha": sha},
            "base": {"sha": base},
        },
        "repository": {"full_name": "org/app"},
    }


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------- 基础行为（无 secret：本地 mock 模式） ----------


def test_webhook_creates_ticket(client) -> None:
    test_client, store = client
    resp = test_client.post("/webhook", json=make_payload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"

    ticket = store.get(body["ticket_id"])
    assert ticket is not None
    assert ticket.status is TicketStatus.CREATED
    assert ticket.repo == "org/app"
    assert ticket.pr_number == 128
    assert ticket.head_sha == "abc123"
    assert ticket.base_sha == "base123"  # 真事件带的对比基准一路带进工单


def test_webhook_ignores_closed(client) -> None:
    test_client, store = client
    resp = test_client.post("/webhook", json=make_payload(action="closed"))

    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
    assert store.list() == []


def test_webhook_rejects_malformed(client) -> None:
    test_client, _ = client
    resp = test_client.post("/webhook", json={"action": "opened"})

    assert resp.status_code == 400


def test_webhook_dedupes_same_sha(client) -> None:
    test_client, store = client
    first = test_client.post("/webhook", json=make_payload()).json()
    second = test_client.post("/webhook", json=make_payload()).json()

    assert first["ticket_id"] == second["ticket_id"]  # 幂等：重复事件同一张单
    assert len(store.list()) == 1


# ---------- 验签（配置 secret 后启用） ----------


def test_valid_signature_accepted(secured_client) -> None:
    test_client, store = secured_client
    body = json.dumps(make_payload()).encode()
    resp = test_client.post(
        "/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": sign("s3cret", body),
            "X-GitHub-Event": "pull_request",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert len(store.list()) == 1


def test_invalid_signature_rejected(secured_client) -> None:
    test_client, store = secured_client
    body = json.dumps(make_payload()).encode()
    resp = test_client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sign("wrong-secret", body)},
    )

    assert resp.status_code == 401
    assert store.list() == []


def test_missing_signature_rejected(secured_client) -> None:
    test_client, store = secured_client
    resp = test_client.post("/webhook", json=make_payload())

    assert resp.status_code == 401
    assert store.list() == []


def test_ping_event_ignored_even_with_valid_signature(secured_client) -> None:
    test_client, store = secured_client
    body = b"{}"
    resp = test_client.post(
        "/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": sign("s3cret", body),
            "X-GitHub-Event": "ping",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert store.list() == []


def test_no_secret_skips_verification(client) -> None:
    test_client, store = client  # secret 为空：本地调试模式，不验签
    resp = test_client.post("/webhook", json=make_payload())

    assert resp.status_code == 200
    assert len(store.list()) == 1
