"""验证持久门禁、真实 HTTP 到业务数据库的链路；不连接付费模型。"""

import importlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from test_api import login, new_thread
from test_graph import ScriptedModel, tool_call

from react_agent import quotas, sessions, storage
from react_agent.api import create_app


def request_for(db_path, user="alice"):
    """功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。"""
    thread = sessions.create_thread(user, db_path)
    return sessions.begin_request(thread, user, "X100无法联网，请建单", db_path)


def admit(db_path, policy, request_id, user="alice", tokens=16000):
    """功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。"""
    return quotas.acquire(policy, user, request_id, db_path, tokens, 160)


def test_concurrent_admission_is_atomic_and_checks_ownership(app_db):
    """功能：ThreadPoolExecutor 同时争抢一个席位，只有一人通过；错误归属通过 raises 验证不会消耗额度。"""
    policy = quotas.DemoLimits(concurrent=1)
    requests = [(user, request_for(app_db, user)) for user in ("alice", "bob", "tech")]

    def attempt(item):
        """功能：模拟一个账号提交；admit 成功返回编号，LimitReached 转为错误码便于核对并发结果。"""
        user, rid = item
        try:
            return admit(app_db, policy, rid, user)
        except quotas.LimitReached as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(attempt, requests))
    assert outcomes.count("MODEL_BUSY") == 2
    with pytest.raises(PermissionError):
        admit(app_db, policy, requests[0][1], "bob")
    assert quotas.overview(policy, app_db)["runs"] == 1


def test_daily_reservation_settlement_and_retry_delta(app_db):
    """功能：检查先预留、仅按重试增量结算及重复结算无效；settle 之后读取 overview，并用新 policy 证明计数持久化。"""
    policy = quotas.DemoLimits(user_daily_tokens=17000)
    rid = request_for(app_db)
    first = admit(app_db, policy, rid)
    usage = {"total_tokens": 1000, "input_tokens": 800, "output_tokens": 200}
    quotas.settle(first, policy, {}, usage, app_db)
    quotas.settle(first, policy, {}, {"total_tokens": 9999}, app_db)
    assert quotas.overview(policy, app_db)["charged_or_reserved_tokens"] == 1000
    second = admit(app_db, policy, rid)
    quotas.settle(second, policy, usage, {"total_tokens": 2000}, app_db)
    assert quotas.overview(policy, app_db)["charged_or_reserved_tokens"] == 2000
    with pytest.raises(quotas.LimitReached) as error:
        admit(app_db, quotas.DemoLimits(user_daily_tokens=17000), rid)
    assert error.value.code == "TOKEN_QUOTA"


def test_same_account_cannot_bypass_seat_limit_with_new_thread(app_db):
    """功能：同账号开新会话仍只能运行一次；admit 在全站尚有席位时拒绝第二次，settle 后才允许继续。"""
    policy = quotas.DemoLimits(concurrent=3)
    first = admit(app_db, policy, request_for(app_db))
    second_request = request_for(app_db)
    with pytest.raises(quotas.LimitReached) as error:
        admit(app_db, policy, second_request)
    assert error.value.code == "MODEL_BUSY"
    quotas.settle(first, policy, {}, {"total_tokens": 0}, app_db)
    assert admit(app_db, policy, second_request)


def test_crash_expires_seat_but_keeps_reservation_and_day_rolls_over(
    app_db, monkeypatch
):
    """功能：模拟崩溃、租约过期及 UTC 跨日；monkeypatch 调时钟，旧预留不退回，次日额度按新日计算。"""
    now = 1800000000.0
    monkeypatch.setattr(quotas.time, "time", lambda: now)
    policy = quotas.DemoLimits(daily_tokens=16000)
    rid = request_for(app_db)
    admit(app_db, policy, rid)
    monkeypatch.setattr(quotas.time, "time", lambda: now + 161)
    assert quotas.overview(policy, app_db)["active"] == 0
    with pytest.raises(quotas.LimitReached) as error:
        admit(app_db, policy, rid)
    assert error.value.code == "TOKEN_QUOTA"
    monkeypatch.setattr(quotas.time, "time", lambda: now + 86400)
    assert admit(app_db, policy, rid)


def test_estimated_unknown_and_money_budget(app_db):
    """功能：估算/未知用量保留预算且按高单价预留；settle/overview 核对金额，再用 acquire 检查金额上限确实阻止执行。"""
    policy = quotas.DemoLimits(
        input_price=Decimal("2"), output_price=Decimal("8"), daily_cost_micro=150000
    )
    rid = request_for(app_db)
    first = admit(app_db, policy, rid)
    quotas.settle(
        first, policy, {}, {"total_tokens": 900, "estimated_tokens": True}, app_db
    )
    info = quotas.overview(policy, app_db)
    assert info["charged_or_reserved_tokens"] == 16000
    assert info["charged_or_reserved_cost"] == 0.128
    with pytest.raises(quotas.LimitReached) as error:
        admit(app_db, policy, rid)
    assert error.value.code == "COST_QUOTA"
    # 新账号和不带金额上限的策略仍会计入站点总用量，未知结果不能退款。
    unlimited_cost = quotas.DemoLimits()
    second = admit(app_db, unlimited_cost, request_for(app_db, "bob"), "bob")
    quotas.settle(second, unlimited_cost, None, None, app_db)
    assert (
        quotas.overview(unlimited_cost, app_db)["charged_or_reserved_tokens"] == 32000
    )


def test_exact_money_and_per_account_rate(app_db):
    """功能：核对精确用量的输入/输出单价以及每账号频率；settle 按差值结算，admit 拒绝一分钟内超额重试。"""
    policy = quotas.DemoLimits(
        per_minute=1, input_price=Decimal("2"), output_price=Decimal("8")
    )
    rid = request_for(app_db)
    first = admit(app_db, policy, rid)
    quotas.settle(
        first,
        policy,
        {"total_tokens": 500, "input_tokens": 400, "output_tokens": 100},
        {"total_tokens": 1500, "input_tokens": 1200, "output_tokens": 300},
        app_db,
    )
    assert quotas.overview(policy, app_db)["charged_or_reserved_cost"] == 0.0032
    with pytest.raises(quotas.LimitReached) as error:
        admit(app_db, policy, rid)
    assert (
        error.value.code == "MODEL_RATE_LIMITED" and 1 <= error.value.retry_after <= 60
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("DEMO_MAX_CONCURRENT", "0"),
        ("DEMO_DAILY_TOKENS", "bad"),
        ("INPUT_PRICE_PER_MILLION", "NaN"),
        ("OUTPUT_PRICE_PER_MILLION", "-1"),
        ("DEMO_DAILY_COST_LIMIT", "10"),
        ("DEMO_MODEL_ENABLED", "yes"),
    ],
)
def test_invalid_operator_configuration_is_rejected(monkeypatch, name, value):
    """功能：参数化错误配置在启动阶段被拒绝；delenv 清除本机单价，setenv 注入异常值，from_env 必须抛错。"""
    for key in (
        "INPUT_PRICE_PER_MILLION",
        "OUTPUT_PRICE_PER_MILLION",
        "DEMO_DAILY_COST_LIMIT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        quotas.DemoLimits.from_env()


def test_http_agent_confirmation_refresh_and_budget_persist(app_db, monkeypatch):
    """功能：完整 HTTP 登录→模型工具→确认→重放→新应用恢复；脚本模型替代远程模型，真实 LangGraph/SQLite 和额度拦截全部执行。"""
    monkeypatch.setenv("MODEL", "deepseek/deepseek-chat")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    monkeypatch.setenv("DEMO_USER_RUNS_PER_MINUTE", "1")
    proposal = tool_call(
        "create_ticket", {"product_model": "X100", "issue_description": "无法联网"}
    )
    proposal.usage_metadata = {
        "input_tokens": 100,
        "output_tokens": 30,
        "total_tokens": 130,
    }
    model = ScriptedModel(
        [
            proposal,
            AIMessage(
                content="请确认",
                usage_metadata={
                    "input_tokens": 150,
                    "output_tokens": 20,
                    "total_tokens": 170,
                },
            ),
        ]
    )
    monkeypatch.setattr(
        importlib.import_module("react_agent.graph"), "load_chat_model", lambda _: model
    )
    with TestClient(
        create_app(app_db, origin="http://testserver"),
        headers={"Origin": "http://testserver"},
    ) as client:
        login(client)
        thread = new_thread(client)
        rid = client.post(
            f"/api/threads/{thread}/requests",
            headers={"Idempotency-Key": "full-agent-001"},
            json={"text": "X100无法联网，请建单"},
        ).json()["request_id"]
        first = client.post(f"/api/requests/{rid}/run")
        assert first.status_code == 200 and first.json()["status"] == "done"
        assert storage.list_tickets(app_db) == []
        card = client.get(f"/api/threads/{thread}").json()["pending_actions"][0]
        endpoint = f"/api/operations/{card['operation_id']}/confirm"
        confirmed = client.post(endpoint, json={"thread_id": thread}).json()
        assert confirmed["success"]
        assert (
            client.post(endpoint, json={"thread_id": thread}).json()["ticket"][
                "ticket_id"
            ]
            == confirmed["ticket"]["ticket_id"]
        )
        assert client.post(f"/api/requests/{rid}/run").json() == first.json()
        assert (
            quotas.overview(client.app.state.model_limits, app_db)[
                "charged_or_reserved_tokens"
            ]
            == 300
        )
        cookie = dict(client.cookies)
    with TestClient(
        create_app(app_db, origin="http://testserver"),
        cookies=cookie,
        headers={"Origin": "http://testserver"},
    ) as fresh:
        fresh.headers["X-CSRF-Token"] = fresh.get("/api/session").json()["csrf_token"]
        data = fresh.get(f"/api/threads/{thread}").json()
        assert data["transcript"] and not data["active_request"]
        ticket_id = confirmed["ticket"]["ticket_id"]
        detail = fresh.get(
            f"/api/tickets/{ticket_id}", params={"thread_id": thread}
        ).json()
        assert detail["ticket"]["status"] == "待处理" and len(detail["history"]) == 1
        rid2 = request_for(app_db)
        denied = fresh.post(f"/api/requests/{rid2}/run")
        assert (
            denied.status_code == 429
            and denied.json()["error_code"] == "MODEL_RATE_LIMITED"
        )
        assert int(denied.headers["Retry-After"]) > 0
        assert sessions.get_request(rid2, "alice", app_db)["status"] == "pending"
        assert len(model.inputs) == 2
        assert len(storage.list_tickets(app_db)) == 1


def test_http_pause_does_not_block_completed_results_or_forms(app_db, monkeypatch):
    """功能：关闭模型仍能使用工单表单和读取已完成结果；post 检查 429，overview 验证拒绝未占用预算。"""
    from test_api import propose

    monkeypatch.setenv("DEMO_MODEL_ENABLED", "false")
    monkeypatch.setenv("MODEL", "deepseek/deepseek-chat")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    with TestClient(
        create_app(app_db, origin="http://testserver"),
        headers={"Origin": "http://testserver"},
    ) as client:
        login(client)
        rid = request_for(app_db)
        assert (
            client.post(f"/api/requests/{rid}/run").json()["error_code"]
            == "MODEL_PAUSED"
        )
        response = propose(client, new_thread(client))
        assert response.status_code == 200
        assert (
            client.post(f"/api/requests/{response.json()['request_id']}/run").json()[
                "status"
            ]
            == "done"
        )
        assert quotas.overview(client.app.state.model_limits, app_db)["runs"] == 0


def test_http_unexpected_failure_releases_seat_conservatively(app_db, monkeypatch):
    """功能：模拟业务入口异常；run 的 finally 仍执行 settle 释放席位，overview 证明预算没有被误退款。"""
    from react_agent import service

    async def crash(*args, **kwargs):
        """功能：抛出确定性异常，制造无法取得用量的失败；不调用远程模型。"""
        raise RuntimeError("test interruption")

    monkeypatch.setattr(service, "run_request", crash)
    monkeypatch.setenv("MODEL", "deepseek/deepseek-chat")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key")
    with TestClient(
        create_app(app_db, origin="http://testserver"),
        headers={"Origin": "http://testserver"},
    ) as client:
        login(client)
        response = client.post(f"/api/requests/{request_for(app_db)}/run")
        assert response.status_code == 500
        summary = quotas.overview(client.app.state.model_limits, app_db)
        assert summary["active"] == 0 and summary["charged_or_reserved_tokens"] == 16000
