import concurrent.futures
import json
import os
import subprocess
import sys

import pytest

from react_agent import storage
from react_agent.knowledge import search as search_faq


# 函数说明：db
# 功能：为每个需要数据库的测试提供独立的 SQLite 文件路径。
# 内部调用：
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
# 装饰器：
#   - @pytest.fixture：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。
@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "tickets.sqlite3")


# 函数说明：test_create_and_query_real_record
# 功能：验证建单真正写入数据库、首尾空白被清理、返回字段与数据库一致，且编号规范化查询可用。
# 内部调用：
#   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - connection.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - connection.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - storage.get_ticket_status()：可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_create_and_query_real_record(db):
    result = storage.create_ticket(" X100 ", " 无法联网 ", "req-1", db)
    assert result["ok"] and not result["reused"]
    ticket = result["ticket"]
    assert ticket["ticket_id"] == "T0001"
    assert ticket["status"] == "待处理"
    with storage.connect(db) as connection:
        row = connection.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket["ticket_id"],)
        ).fetchone()
        assert dict(row) == ticket
    assert storage.get_ticket_status(" t1 ", db)["ticket"] == ticket


# 函数说明：test_missing_fields_do_not_write
# 功能：检查缺型号、缺描述和两者都缺失的情况，确保返回缺失字段且不写工单。
# 内部调用：
#   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 装饰器：
#   - @pytest.mark.parametrize：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
@pytest.mark.parametrize(
    "model,issue,missing",
    [
        ("", "无法联网", ["product_model"]),
        ("X100", "  ", ["issue_description"]),
        (None, "", ["product_model", "issue_description"]),
    ],
)
def test_missing_fields_do_not_write(db, model, issue, missing):
    result = storage.create_ticket(model, issue, "req-1", db)
    assert result["error"] == "missing_fields"
    assert result["fields"] == missing
    assert storage.list_tickets(db) == []


# 函数说明：test_invalid_input_does_not_write
# 功能：检查型号超长、描述超长和请求编号缺失时返回对应错误，并阻止写入。
# 内部调用：
#   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 装饰器：
#   - @pytest.mark.parametrize：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
@pytest.mark.parametrize(
    "model,issue,request_id,error",
    [
        ("X" * 81, "无法联网", "req-1", "invalid_fields"),
        ("X100", "问" * 2001, "req-1", "invalid_fields"),
        ("X100", "无法联网", "", "missing_request_id"),
    ],
)
def test_invalid_input_does_not_write(db, model, issue, request_id, error):
    assert storage.create_ticket(model, issue, request_id, db)["error"] == error
    assert storage.list_tickets(db) == []


# 函数说明：test_repeated_request_returns_original
# 功能：验证同一请求编号和同一组参数重复提交时，返回原记录并标记复用。
# 内部调用：
#   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_repeated_request_returns_original(db):
    first = storage.create_ticket("X100", "无法联网", "req-1", db)
    second = storage.create_ticket("X100", "无法联网", "req-1", db)
    assert second["ticket"] == first["ticket"]
    assert second["reused"]
    assert len(storage.list_tickets(db)) == 1


# 函数说明：test_changed_retry_payload_is_a_conflict
# 功能：验证复用请求编号却改变业务参数时返回冲突，不覆盖原记录，也不新增工单。
# 内部调用：
#   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_changed_retry_payload_is_a_conflict(db):
    original = storage.create_ticket("X100", "无法联网", "req-1", db)["ticket"]
    retry = storage.create_ticket("X200", "无法开机", "req-1", db)
    assert retry["error"] == "request_conflict"
    assert retry["ticket"] == original
    assert storage.list_tickets(db) == [original]


# 函数说明：test_concurrent_requests_are_atomic
# 功能：并发提交 16 次请求，分别检查相同编号只建一张、不同编号各建一张，验证事务和去重约束。
# 内部调用：
#   - concurrent.futures.ThreadPoolExecutor()：建立有界线程池，模拟多个调用同时访问同一个数据库或确认操作。
#   - range()：产生整数序列，供有界重试、模拟轮次或并发任务循环使用。
#   - pool.map()：把输入逐个交给指定函数并在线程池中执行，按输入顺序收集结果。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
#   - all()：检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
# 间接调用 / 回调：
#   - submit：由 pool.map 调用/注册：在线程池中执行一次建单，根据外层测试模式使用同一个编号或各自不同的编号。
# 装饰器：
#   - @pytest.mark.parametrize：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_requests_are_atomic(db, same_request):
    # 函数说明：test_concurrent_requests_are_atomic.submit
    # 功能：在线程池中执行一次建单，根据外层测试模式使用同一个编号或各自不同的编号。
    # 内部调用：
    #   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
    def submit(index):
        return storage.create_ticket(
            "X100", "无法联网", "same" if same_request else f"req-{index}", db
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(16)))
    assert all(result["ok"] for result in results)
    assert len(storage.list_tickets(db)) == (1 if same_request else 16)
    assert sum(not result["reused"] for result in results) == (
        1 if same_request else 16
    )


# 函数说明：test_query_missing_and_invalid_ids
# 功能：检查格式正确但不存在的编号，以及包含 SQL 片段的非法编号，都返回明确错误而不生成工单。
# 内部调用：
#   - storage.get_ticket_status()：可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_query_missing_and_invalid_ids(db):
    assert storage.get_ticket_status("T9999", db)["error"] == "not_found"
    assert (
        storage.get_ticket_status("T0001' OR 1=1 --", db)["error"]
        == "invalid_ticket_id"
    )
    assert storage.list_tickets(db) == []


# 函数说明：test_survives_new_process_and_retry
# 功能：创建记录后启动新的 Python 进程重试同一请求，验证数据和请求去重不依赖当前进程内存。
# 内部调用：
#   - storage.create_ticket()：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
#   - subprocess.check_output()：启动新的 Python 进程并读取标准输出，验证数据持久化与重试不依赖当前内存。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
# 补充：子进程 code 字符串调用 storage.create_ticket() 重试同一请求，json.dumps()/print() 输出结果；这不是在父进程里再次执行。
def test_survives_new_process_and_retry(db):
    original = storage.create_ticket("X100", "无法联网", "req-1", db)["ticket"]
    code = "from react_agent.storage import create_ticket; import json,sys; print(json.dumps(create_ticket('X100','无法联网','req-1',sys.argv[1])))"
    output = subprocess.check_output(
        [sys.executable, "-c", code, db],
        env={**os.environ, "LANGSMITH_TRACING": "false"},
    )
    result = json.loads(output)
    assert result["ticket"] == original
    assert result["reused"]
    assert len(storage.list_tickets(db)) == 1


# 函数说明：test_faq_keyword_search
# 功能：验证中文、英文网络词和蓝牙检索命中正确 FAQ；X100 蓝牙、无资料故障和空查询均不能返回不适用资料。
# 内部调用：
#   - search_faq()：调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_faq_keyword_search():
    """检验型号硬过滤、来源和无匹配错误，直接调用本地检索。"""
    assert search_faq("X100 连不上网")["matches"][0]["id"] == "FAQ-001"
    assert search_faq("Wi-Fi 无法使用", "X100")["matches"][0]["id"] == "FAQ-001"
    assert search_faq("蓝牙配对", "X200")["matches"][0]["id"] == "FAQ-003"
    assert search_faq("X100蓝牙配对")["matches"] == []
    assert search_faq("屏幕出现紫色竖线", "X100")["matches"] == []
    assert search_faq("")["matches"] == []
