"""关键业务验证：事务、确认绑定、状态机、权限、相似单、审计和并发。"""

import concurrent.futures
import json
import sqlite3

import pytest
from conftest import new_request

from react_agent import actions, auth, sessions, storage
from react_agent.context import Context


# 函数说明：proposal
# 功能：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
# 内部调用：
#   - new_request()：结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
def proposal(ctx, action="create_ticket", **payload):
    """为测试创建真实请求并调用 propose；每次提案均需独立应用请求。"""
    new_request(ctx)
    return actions.propose(
        ctx,
        action,
        payload or {"product_model": "X100", "issue_description": "无法联网"},
    )


# 函数说明：created
# 功能：通过提案加显式确认建立测试工单，不绕过执行层。
# 内部调用：
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
def created(ctx):
    """通过提案加显式确认建立测试工单，不绕过执行层。"""
    pending = proposal(ctx)
    return actions.confirm_action(ctx, pending["operation_id"])["ticket"]


# 函数说明：other_context
# 功能：为另一已有测试账号创建独立会话。
# 内部调用：
#   - sessions.create_thread()：验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
def other_context(ctx, user):
    """为另一已有测试账号创建独立会话。"""
    return Context(
        user_id=user,
        thread_id=sessions.create_thread(user, ctx.db_path),
        db_path=ctx.db_path,
    )


# 函数说明：test_atomic_migration_preserves_legacy_rows
# 功能：建立旧版单表数据库，验证自动迁移保留原工单、设置 legacy 归属，并让新编号接着旧编号递增。
# 内部调用：
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - sqlite3.connect()：打开指定 SQLite 文件连接；迁移测试也用它建立原始旧表，绕开应用迁移逻辑。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_atomic_migration_preserves_legacy_rows(tmp_path):
    db_path = str(tmp_path / "old.db")
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE tickets(ticket_id TEXT PRIMARY KEY,request_id TEXT UNIQUE,product_model TEXT,issue_description TEXT,status TEXT,created_at TEXT)"
        )
        db.execute(
            "INSERT INTO tickets VALUES ('T0123','old','X100','故障','待处理','2026-01-01')"
        )
    ticket = storage.list_tickets(db_path)[0]
    assert ticket["ticket_id"] == "T0123" and ticket["owner_id"] == "legacy"
    assert (
        storage.create_ticket("X100", "新问题", "next", db_path)["ticket"]["ticket_id"]
        == "T0124"
    )


# 函数说明：test_same_confirmation_concurrent_creates_once
# 功能：并发确认同一个 operation_id 十二次，验证只新建一张工单、一条创建审计，其余调用复用结果。
# 内部调用：
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - concurrent.futures.ThreadPoolExecutor()：建立有界线程池，模拟多个调用同时访问同一个数据库或确认操作。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - range()：产生整数序列，供有界重试、模拟轮次或并发任务循环使用。
#   - pool.map()：把输入逐个交给指定函数并在线程池中执行，按输入顺序收集结果。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
#   - all()：检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。
#   - result.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - actions.read_ticket()：调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。
# 匿名函数：
#   - lambda _: actions.confirm_action(ctx, pending['operation_id'])：由线程池调用；忽略输入序号，让每个任务确认同一个操作以验证幂等和事务。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_same_confirmation_concurrent_creates_once(ctx):
    pending = proposal(ctx)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: actions.confirm_action(ctx, pending["operation_id"]),
                range(12),
            )
        )
    assert all(result["success"] for result in results)
    assert sum(not result.get("reused", False) for result in results) == 1
    assert len(storage.list_tickets(ctx.db_path)) == 1
    assert len(actions.read_ticket(ctx, "T0001", history=True)["history"]) == 1


# 函数说明：test_confirmation_expiry_tampering_and_cancel
# 功能：分别模拟确认过期、冻结参数被篡改和用户撤销，验证后续确认被拒绝，工单表保持为空。
# 内部调用：
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - json.dumps()：把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 装饰器：
#   - @pytest.mark.parametrize：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
@pytest.mark.parametrize(
    "change,error",
    [
        ("expiry", "confirmation_expired"),
        ("payload", "payload_changed"),
        ("cancel", "confirmation_expired"),
    ],
)
def test_confirmation_expiry_tampering_and_cancel(ctx, change, error):
    pending = proposal(ctx)
    with storage.connect(ctx.db_path) as db:
        if change == "expiry":
            db.execute("UPDATE pending_actions SET expires_at='2000-01-01'")
        elif change == "payload":
            db.execute(
                "UPDATE pending_actions SET payload=?",
                (json.dumps({"product_model": "X200"}),),
            )
    if change == "cancel":
        actions.confirm_action(ctx, pending["operation_id"], cancel=True)
    outcome = actions.confirm_action(ctx, pending["operation_id"])
    assert outcome["error"] == error
    assert not storage.list_tickets(ctx.db_path)


# 函数说明：test_cross_user_and_cross_thread_confirmation
# 功能：尝试用其他客户或同一客户的另一会话确认卡片，验证用户与会话绑定不能被绕过。
# 内部调用：
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - other_context()：为另一已有测试账号创建独立会话。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_cross_user_and_cross_thread_confirmation(ctx):
    pending = proposal(ctx)
    bob = other_context(ctx, "bob")
    alice_other = other_context(ctx, "alice")
    for other in (bob, alice_other):
        assert (
            actions.confirm_action(other, pending["operation_id"])["error"]
            == "forbidden"
        )
    assert not storage.list_tickets(ctx.db_path)


# 函数说明：test_new_message_invalidates_old_confirmation
# 功能：先提出建单，再发送修改型号的新消息，验证旧确认卡片失效。
# 内部调用：
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - new_request()：结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_new_message_invalidates_old_confirmation(ctx):
    pending = proposal(ctx)
    new_request(ctx, "不对，应该是X200")
    assert (
        actions.confirm_action(ctx, pending["operation_id"])["error"]
        == "confirmation_expired"
    )


# 函数说明：test_changed_retry_conflicts
# 功能：同一请求改成另一型号重试时应返回冲突；再确认原卡片，仍按原型号创建。
# 内部调用：
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_changed_retry_conflicts(ctx):
    pending = proposal(ctx)
    outcome = actions.propose(
        ctx, "create_ticket", {"product_model": "X200", "issue_description": "无法联网"}
    )
    assert outcome["error"] == "request_conflict"
    assert (
        actions.confirm_action(ctx, pending["operation_id"])["ticket"]["product_model"]
        == "X100"
    )


# 函数说明：test_customer_cannot_see_other_customer_data
# 功能：创建属于 alice 的工单后改用 bob 查询，验证编号查询、全量筛选和会话读取都不泄露他人数据。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - other_context()：为另一已有测试账号创建独立会话。
#   - actions.read_ticket()：调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。
#   - actions.search_tickets()：按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。
#   - pytest.raises()：声明代码块应抛出指定异常；未抛出或异常类型不对都会使测试失败。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_customer_cannot_see_other_customer_data(ctx):
    created(ctx)
    bob = other_context(ctx, "bob")
    assert actions.read_ticket(bob, "T0001")["error"] == "not_found"
    assert actions.search_tickets(bob, mine=False)["tickets"] == []
    with pytest.raises(PermissionError):
        sessions.get_thread(ctx.thread_id, "bob", ctx.db_path)


# 函数说明：test_assignment_priority_and_duplicate_detection
# 功能：验证按专长自动分派、同型号同故障相似单提示、重复建单额外确认，以及安全故障的紧急优先级。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_assignment_priority_and_duplicate_detection(ctx):
    ticket = created(ctx)
    assert ticket["assigned_to"] == "tech"
    pending = proposal(ctx)
    assert pending["payload"]["duplicates"][0]["ticket_id"] == ticket["ticket_id"]
    assert (
        actions.confirm_action(ctx, pending["operation_id"])["error"]
        == "duplicate_confirmation_required"
    )
    assert actions.confirm_action(ctx, pending["operation_id"], accept_duplicate=True)[
        "success"
    ]
    urgent = proposal(
        ctx, product_model="X100", issue_description="设备冒烟", impact="all"
    )
    assert urgent["payload"]["priority"] == "紧急"


# 函数说明：test_new_duplicate_during_confirmation_requires_new_proposal
# 功能：在卡片生成后由另一会话创建相似工单，验证原卡片即使勾选重复确认也必须重新发起核对。
# 内部调用：
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - other_context()：为另一已有测试账号创建独立会话。
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_new_duplicate_during_confirmation_requires_new_proposal(ctx):
    pending = proposal(ctx)
    other = other_context(ctx, "alice")
    created(other)
    assert (
        actions.confirm_action(ctx, pending["operation_id"], accept_duplicate=True)[
            "error"
        ]
        == "duplicate_changed"
    )


# 函数说明：test_full_lifecycle_and_audit
# 功能：轮换维修人员与客户身份走完五阶段生命周期，验证每次确认后的状态，以及五条审计的实际操作人。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - other_context()：为另一已有测试账号创建独立会话。
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - actions.read_ticket()：调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_full_lifecycle_and_audit(ctx):
    ticket = created(ctx)
    tech = other_context(ctx, "tech")
    for person, target in [
        (tech, "处理中"),
        (tech, "待用户确认"),
        (ctx, "已解决"),
        (ctx, "已关闭"),
    ]:
        pending = proposal(
            person,
            "update_ticket_status",
            ticket_id=ticket["ticket_id"],
            new_status=target,
            note="测试处理说明",
        )
        assert pending["success"], pending
        outcome = actions.confirm_action(person, pending["operation_id"])
        assert outcome["ticket"]["status"] == target
    history = actions.read_ticket(ctx, ticket["ticket_id"], history=True)["history"]
    assert len(history) == 5
    assert [entry["operator_id"] for entry in history] == [
        "alice",
        "tech",
        "tech",
        "alice",
        "alice",
    ]


# 函数说明：test_customer_cannot_start_or_skip_repair
# 功能：对多种目标状态参数化测试，验证客户不能从待处理直接开始、完成或跳过维修，也不能设置未知状态。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - storage.get_ticket_status()：可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。
# 装饰器：
#   - @pytest.mark.parametrize：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
@pytest.mark.parametrize("target", ["处理中", "已解决", "待用户确认", "退款成功"])
def test_customer_cannot_start_or_skip_repair(ctx, target):
    ticket = created(ctx)
    outcome = proposal(
        ctx,
        "update_ticket_status",
        ticket_id=ticket["ticket_id"],
        new_status=target,
        note="用户自称维修人员",
    )
    assert not outcome["success"]
    assert (
        storage.get_ticket_status(ticket["ticket_id"], ctx.db_path)["ticket"]["status"]
        == "待处理"
    )


# 函数说明：test_stale_version_and_role_recheck
# 功能：分别在卡片生成后修改工单版本、降低维修账号权限，验证确认时会重新检查版本和角色。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - other_context()：为另一已有测试账号创建独立会话。
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_stale_version_and_role_recheck(ctx):
    ticket = created(ctx)
    admin = other_context(ctx, "admin")
    tech = other_context(ctx, "tech")
    pending = proposal(
        tech,
        "update_ticket_status",
        ticket_id=ticket["ticket_id"],
        new_status="处理中",
        note="开始维修",
    )
    supplement = proposal(
        admin,
        "supplement_ticket",
        ticket_id=ticket["ticket_id"],
        description="新故障线索",
    )
    assert actions.confirm_action(admin, supplement["operation_id"])["success"]
    assert (
        actions.confirm_action(tech, pending["operation_id"])["error"] == "stale_ticket"
    )
    pending = proposal(
        tech,
        "update_ticket_status",
        ticket_id=ticket["ticket_id"],
        new_status="处理中",
        note="开始维修",
    )
    with storage.connect(ctx.db_path) as db:
        db.execute("UPDATE users SET role='customer' WHERE user_id='tech'")
    assert actions.confirm_action(tech, pending["operation_id"])["error"] == "forbidden"


# 函数说明：test_supplement_handoff_priority_assignment_cancel
# 功能：通过真实确认入口依次补充信息、申请人工、调整优先级、分派和取消，核对持久字段及取消后的状态限制。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - other_context()：为另一已有测试账号创建独立会话。
#   - actions.read_ticket()：调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_supplement_handoff_priority_assignment_cancel(ctx):
    ticket = created(ctx)
    for action, payload in [
        (
            "supplement_ticket",
            {
                "description": "重启无效",
                "contact": "test@example.invalid",
                "device_info": "SN-demo",
            },
        ),
        ("handoff_ticket", {"note": "排查失败"}),
    ]:
        pending = proposal(ctx, action, ticket_id=ticket["ticket_id"], **payload)
        assert actions.confirm_action(ctx, pending["operation_id"])["success"]
    support = other_context(ctx, "support")
    for action, payload in [
        ("set_ticket_priority", {"priority": "高"}),
        ("assign_ticket", {"assignee_id": "tech"}),
    ]:
        pending = proposal(support, action, ticket_id=ticket["ticket_id"], **payload)
        assert actions.confirm_action(support, pending["operation_id"])["success"]
    saved = actions.read_ticket(ctx, ticket["ticket_id"])["ticket"]
    assert (
        saved["manual"]
        and saved["contact"] == "test@example.invalid"
        and "重启无效" in saved["issue_description"]
    )
    assert saved["priority"] == "高"
    pending = proposal(ctx, "cancel_ticket", ticket_id=ticket["ticket_id"])
    assert (
        actions.confirm_action(ctx, pending["operation_id"])["ticket"]["status"]
        == "已关闭"
    )


# 函数说明：test_search_filters
# 功能：检查型号、编号、状态和日期过滤，并验证无效日期及逆序日期范围返回错误。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - actions.search_tickets()：按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_search_filters(ctx):
    created(ctx)
    assert (
        len(
            actions.search_tickets(ctx, product_model="X100", status="待处理")[
                "tickets"
            ]
        )
        == 1
    )
    assert actions.search_tickets(ctx, product_model="X200")["tickets"] == []
    assert actions.search_tickets(ctx, created_from="2099-01-01")["tickets"] == []
    assert (
        actions.search_tickets(ctx, created_from="wrong")["error"] == "invalid_fields"
    )
    assert (
        actions.search_tickets(ctx, ticket_id="' OR 1=1")["error"]
        == "invalid_ticket_id"
    )


# 函数说明：test_registration_cannot_self_promote
# 功能：验证普通注册不能创建管理员，首次初始化不能重复使用，以及登录令牌在退出后失效。
# 内部调用：
#   - auth.create_user()：事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。
#   - auth.login()：调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。
#   - auth.authenticate()：调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。
#   - auth.logout()：调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_registration_cannot_self_promote(app_db):
    assert (
        auth.create_user("eve", "test-password", "admin", app_db)["error"]
        == "forbidden"
    )
    assert (
        auth.create_user("eve", "test-password", "admin", app_db, bootstrap=True)[
            "error"
        ]
        == "forbidden"
    )
    assert not auth.login("alice", "wrong-password", app_db)["success"]
    logged = auth.login("alice", "test-password", app_db)
    assert auth.authenticate(logged["token"], app_db)["role"] == "customer"
    auth.logout(logged["token"], app_db)
    assert auth.authenticate(logged["token"], app_db) is None


# 函数说明：test_legacy_other_issue_is_detected_as_duplicate
# 功能：把已有工单类别改成旧版 other，验证从原始描述补判故障类别后仍能识别相似工单。
# 内部调用：
#   - created()：通过提案加显式确认建立测试工单，不绕过执行层。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - proposal()：为测试创建真实请求并调用 propose；每次提案均需独立应用请求。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_legacy_other_issue_is_detected_as_duplicate(ctx):
    created(ctx)
    with storage.connect(ctx.db_path) as db:
        db.execute("UPDATE tickets SET issue_type='other'")
    pending = proposal(
        ctx,
        product_model="X100",
        issue_description="我的 X100 无法联网，请再帮我创建一张售后工单",
    )
    assert pending["payload"]["duplicates"][0]["ticket_id"] == "T0001"
    assert (
        actions.confirm_action(ctx, pending["operation_id"])["error"]
        == "duplicate_confirmation_required"
    )
