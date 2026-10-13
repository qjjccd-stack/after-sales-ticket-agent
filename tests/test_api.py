"""真实 API/数据库的安全与恢复测试；模型用脚本替换，不产生外部模型费用。"""

import importlib
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from test_graph import ScriptedModel, tool_call

from react_agent import auth, sessions, storage
from react_agent.api import COOKIE, create_app


@pytest.fixture
def client(app_db):
    """功能：TestClient 启动完整 API 生命周期；create_app 指向测试库，Origin 与服务地址一致。"""
    with TestClient(
        create_app(app_db, origin="http://testserver"),
        headers={"Origin": "http://testserver"},
    ) as value:
        yield value


def login(client, name="alice"):
    """功能：模拟网页登录；post 换取 Cookie，保存 CSRF 证明到后续请求头，并断言登录成功。"""
    response = client.post(
        "/api/login", json={"user_id": name, "password": "test-password"}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


def new_thread(client):
    """功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。"""
    response = client.post("/api/threads")
    assert response.status_code == 201, response.text
    return response.json()["thread_id"]


def propose(client, thread, key="submission-001", model="X100"):
    """功能：发送有幂等键的手工建单提案；post 仅生成确认卡片，不直接写工单。"""
    return client.post(
        f"/api/threads/{thread}/proposals",
        headers={"Idempotency-Key": key},
        json={
            "action": "create_ticket",
            "payload": {"product_model": model, "issue_description": "无法联网"},
        },
    )


def test_cookie_refresh_csrf_and_logout(client, app_db):
    """功能：验证凭据不进 URL/JSON，跨客户端刷新可恢复，CSRF 与 Origin 拦截修改，logout 撤销令牌；调用 login、TestClient、get/post。"""
    response = login(client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    token = client.cookies.get(COOKIE)
    assert token not in response.text
    with TestClient(
        client.app, cookies={COOKIE: token}, headers={"Origin": "http://testserver"}
    ) as fresh:
        session = fresh.get("/api/session")
        assert session.status_code == 200
        assert fresh.post("/api/threads").status_code == 403
        fresh.headers["X-CSRF-Token"] = session.json()["csrf_token"]
        assert (
            fresh.post(
                "/api/threads", headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert fresh.post("/api/threads").status_code == 201
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/session").status_code == 401
    assert auth.authenticate(token, app_db) is None


def test_secure_cookie_and_origin_configuration(app_db):
    """功能：验证 HTTPS Cookie 与非本机配置限制；create_app 拒绝明文公网配置，TestClient 检查真实 Set-Cookie 头。"""
    with pytest.raises(ValueError):
        create_app(app_db, origin="http://tickets.example.com")
    with TestClient(
        create_app(app_db, origin="https://tickets.example.com"),
        base_url="https://tickets.example.com",
        headers={"Origin": "https://tickets.example.com"},
    ) as client:
        response = login(client)
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/api/session").status_code == 200


def test_login_rotation_url_rejected_and_password_not_echoed(client, app_db):
    """功能：登录轮换旧令牌、拒绝 URL 登录及多余角色；auth.authenticate 验证旧会话撤销，响应不得包含密码。"""
    login(client)
    old = client.cookies.get(COOKIE)
    login(client)
    assert auth.authenticate(old, app_db) is None
    client.cookies.clear()
    assert client.get("/api/session", params={"session": old}).status_code == 401
    response = client.post(
        "/api/login",
        json={"user_id": "alice", "password": "private-test-secret", "role": "admin"},
    )
    assert response.status_code == 422 and "private-test-secret" not in response.text
    assert (
        client.post(
            "/api/login",
            json={"user_id": "alice", "password": "test-password"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )


def test_request_submission_replays_or_conflicts(client, app_db):
    """功能：检查同键同内容仅保存一条消息，同键异内容冲突；post 重放后 get_thread 检查 transcript。"""
    login(client)
    thread = new_thread(client)
    endpoint = f"/api/threads/{thread}/requests"
    headers = {"Idempotency-Key": "message-key-001"}
    first = client.post(endpoint, json={"text": "X100无法联网"}, headers=headers)
    second = client.post(endpoint, json={"text": "X100无法联网"}, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["request_id"] == second.json()["request_id"]
    assert len(sessions.get_thread(thread, "alice", app_db)["transcript"]) == 1
    assert (
        client.post(endpoint, json={"text": "改成X200"}, headers=headers).status_code
        == 409
    )
    assert client.post(endpoint, json={"text": "新消息"}).status_code == 422


def test_concurrent_submission_has_one_request(ctx):
    """功能：验证数据库事务承受同键并发提交；线程池调用 begin_request，检查所有请求编号一致及消息仅一份。"""

    def submit(_):
        """功能：模拟重复客户端；调用 begin_request 传入相同提交键和内容。"""
        return sessions.begin_request(
            ctx.thread_id,
            ctx.user_id,
            "X100无法联网",
            ctx.db_path,
            client_key="same-http-submission",
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(submit, range(6)))
    assert len(set(ids)) == 1
    assert (
        len(sessions.get_thread(ctx.thread_id, ctx.user_id, ctx.db_path)["transcript"])
        == 1
    )


def test_http_confirmation_is_required_and_idempotent(client, app_db):
    """功能：从 HTTP 提案到确认验证真实库；重复提交/确认均复用结果，SELECT 验证一张工单和一条创建审计。"""
    login(client)
    thread = new_thread(client)
    first = propose(client, thread)
    repeated = propose(client, thread)
    assert first.status_code == repeated.status_code == 200
    operation = first.json()["operation_id"]
    assert operation == repeated.json()["operation_id"]
    assert storage.list_tickets(app_db) == []
    display = client.get(f"/api/threads/{thread}").json()["transcript"][0]["content"]
    assert "设备型号：X100" in display and '"payload"' not in display
    body = {"thread_id": thread}
    created = client.post(f"/api/operations/{operation}/confirm", json=body)
    again = client.post(f"/api/operations/{operation}/confirm", json=body)
    assert created.status_code == again.status_code == 200
    assert created.json()["ticket"]["ticket_id"] == again.json()["ticket"]["ticket_id"]
    with storage.connect(app_db) as db:
        assert db.execute("SELECT count(*) FROM tickets").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM ticket_events").fetchone()[0] == 1


def test_cross_user_forged_identity_and_permission_change(client, app_db):
    """功能：验证越权会话/确认/管理员访问被拒绝；Cookie 切换用户，SQL 改真实角色后接口立即收回权限。"""
    login(client)
    thread = new_thread(client)
    operation = propose(client, thread).json()["operation_id"]
    assert (
        client.post(
            f"/api/operations/{operation}/confirm",
            json={"thread_id": thread, "confirmed": True},
        ).status_code
        == 422
    )
    login(client, "bob")
    assert client.get(f"/api/threads/{thread}").status_code == 403
    assert (
        client.post(
            f"/api/operations/{operation}/confirm", json={"thread_id": thread}
        ).status_code
        == 403
    )
    assert client.get("/api/admin/users").status_code == 403
    assert (
        client.post(
            "/api/admin/users",
            json={"user_id": "newadmin", "password": "test-password", "role": "admin"},
        ).status_code
        == 403
    )
    login(client, "admin")
    assert client.get("/api/admin/users").status_code == 200
    with storage.connect(app_db) as db:
        db.execute("UPDATE users SET role='customer' WHERE user_id='admin'")
    assert client.get("/api/admin/users").status_code == 403
    assert storage.list_tickets(app_db) == []


def test_staff_creation_and_proposal_field_whitelist(client):
    """功能：管理员创建人员可用，业务载荷无法伪造操作者或版本；调用 login、new_thread、post 检查 HTTP 边界。"""
    login(client, "admin")
    assert (
        client.post(
            "/api/admin/users",
            json={
                "user_id": "newtech",
                "password": "test-password",
                "role": "technician",
            },
        ).status_code
        == 200
    )
    thread = new_thread(client)
    response = client.post(
        f"/api/threads/{thread}/proposals",
        headers={"Idempotency-Key": "fake-role-test"},
        json={
            "action": "create_ticket",
            "payload": {
                "product_model": "X100",
                "issue_description": "坏了",
                "operator_id": "admin",
            },
        },
    )
    assert response.status_code == 422


def test_http_checkpoint_retry_uses_original_request(client, app_db, monkeypatch):
    """功能：通过 API 故意中断真实 LangGraph 再重试；ScriptedModel 替换远程模型，数据库检查只有一张卡片且预算累计。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    monkeypatch.setenv("MODEL", "deepseek/deepseek-chat")
    model = ScriptedModel(
        [
            tool_call(
                "create_ticket",
                {"product_model": "X100", "issue_description": "无法联网"},
            ),
            RuntimeError("interrupted"),
            AIMessage(content="请确认"),
        ]
    )
    monkeypatch.setattr(
        importlib.import_module("react_agent.graph"), "load_chat_model", lambda _: model
    )
    login(client)
    thread = new_thread(client)
    rid = client.post(
        f"/api/threads/{thread}/requests",
        headers={"Idempotency-Key": "model-retry-001"},
        json={"text": "X100无法联网，请建单"},
    ).json()["request_id"]
    first = client.post(f"/api/requests/{rid}/run")
    assert first.json()["status"] == "failed"
    resumed = client.post(f"/api/requests/{rid}/run")
    assert resumed.json()["status"] == "done"
    assert resumed.json()["usage"]["tool_calls"] == 1
    assert client.post(f"/api/requests/{rid}/run").json() == resumed.json()
    data = client.get(f"/api/threads/{thread}").json()
    assert len(data["pending_actions"]) == 1 and not storage.list_tickets(app_db)


def test_login_rate_limit_persists_between_app_instances(client, app_db, monkeypatch):
    """功能：验证限流存数据库且时间窗口能恢复；consume_login_budget 预先占满，换应用后 login 仍返回 429，更新时间后恢复。"""
    for _ in range(10):
        assert auth.consume_login_budget("alice", app_db)
    with TestClient(
        create_app(app_db, origin="http://testserver"),
        headers={"Origin": "http://testserver"},
    ) as other:
        assert (
            other.post(
                "/api/login", json={"user_id": "alice", "password": "test-password"}
            ).status_code
            == 429
        )
    with storage.connect(app_db) as db:
        db.execute("UPDATE auth_limits SET started_at=0")
    assert login(client).status_code == 200


def test_static_page_and_health_do_not_expose_secrets(client):
    """功能：确认页面与健康检查可用，未登录不能读业务；get 检查 CSP、页面资源和身份边界。"""
    assert client.get("/health/ready").status_code == 200
    page = client.get("/")
    assert page.status_code == 200
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/threads").status_code == 401
    assert client.get("/api/admin/metrics").status_code == 401


def test_unexpected_error_does_not_expose_payload(client, monkeypatch, caplog):
    """功能：模拟内部异常，确认响应和日志不泄露正文；setattr 替换会话读取，caplog 检查日志仍有跟踪编号。"""
    login(client)

    def broken(*args, **kwargs):
        """功能：抛出含模拟私人文本的 RuntimeError，验证 HTTP 统一异常边界。"""
        raise RuntimeError("private-customer-description")

    monkeypatch.setattr(sessions, "list_threads", broken)
    with caplog.at_level(logging.INFO, logger="uvicorn.error.ticket_http"):
        response = client.get("/api/threads?private=private-customer-description")
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"
    assert response.headers["x-request-id"] in caplog.text
    assert "RuntimeError" in caplog.text
    assert "private-customer-description" not in response.text + caplog.text
