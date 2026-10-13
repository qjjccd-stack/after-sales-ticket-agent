"""Streamlit 页面回归：认证、确认按钮、刷新恢复以及工单工作台。"""

import importlib

from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest
from test_graph import ScriptedModel, tool_call

from react_agent import auth, sessions, storage


# 函数说明：page
# 功能：配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。
# 内部调用：
#   - monkeypatch.setenv()：在测试期间临时设置环境变量，例如数据库路径与模拟密钥；测试结束自动还原。
#   - importlib.import_module()：按模块名导入模块；评测/测试用来替换模型加载入口，不加载用户输入的任意模块。
#   - monkeypatch.setattr()：在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。
#   - auth.login()：调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - AppTest.from_file()：从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。
#   - app.run()：执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。
# 匿名函数：
#   - lambda _: model：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。
def page(monkeypatch, app_db, model=None, ready=True):
    """配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。"""
    monkeypatch.setenv("TICKET_DB_PATH", app_db)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-test-key" if ready else "")
    monkeypatch.setenv("MODEL", "deepseek/deepseek-chat")
    if model:
        monkeypatch.setattr(
            importlib.import_module("react_agent.graph"),
            "load_chat_model",
            lambda _: model,
        )
    token = auth.login("alice", "test-password", app_db)["token"]
    app = AppTest.from_file(str(storage.ROOT / "app.py"), default_timeout=30)
    app.session_state["auth_token"] = token
    return app.run(), token


# 函数说明：test_page_without_credentials
# 功能：模拟缺少模型密钥，验证聊天输入禁用，但已登录用户仍能打开没有工单的工作台。
# 内部调用：
#   - page()：配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_page_without_credentials(monkeypatch, app_db):
    app, _ = page(monkeypatch, app_db, ready=False)
    assert not app.exception
    assert app.chat_input[0].disabled
    assert any("暂无工单" in item.value for item in app.caption)


# 函数说明：test_page_requires_login
# 功能：不提供登录令牌启动页面，验证只显示账号登录输入，不显示售后聊天。
# 内部调用：
#   - monkeypatch.setenv()：在测试期间临时设置环境变量，例如数据库路径与模拟密钥；测试结束自动还原。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - AppTest.from_file()：从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。
#   - AppTest.from_file(...).run()：执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_page_requires_login(monkeypatch, app_db):
    monkeypatch.setenv("TICKET_DB_PATH", app_db)
    app = AppTest.from_file(str(storage.ROOT / "app.py"), default_timeout=20).run()
    assert not app.exception
    assert not app.chat_input
    assert app.text_input[0].label == "账号"


def test_old_url_session_is_not_accepted(monkeypatch, app_db):
    """功能：防止旧 URL 登录方式复活；auth.login 取有效测试令牌，AppTest 只通过查询参数传入，仍应显示登录页并清除参数。"""
    monkeypatch.setenv("TICKET_DB_PATH", app_db)
    token = auth.login("alice", "test-password", app_db)["token"]
    app = AppTest.from_file(str(storage.ROOT / "app.py"), default_timeout=20)
    app.query_params["session"] = token
    app.run()
    assert not app.chat_input and "session" not in app.query_params


# 函数说明：test_confirmation_card_restores_after_refresh
# 功能：用脚本模型提出建单，在新的页面实例中恢复相同登录与会话，点击确认后检查只创建一张工单且卡片消失。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - ScriptedModel()：构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。
#   - page()：配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。
#   - app.chat_input[0].set_value()：设置测试页面控件的值；后续 run 才触发完整页面处理。
#   - app.chat_input[0].set_value(...).run()：执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - sessions.list_threads()：参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - AppTest.from_file()：从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。
#   - refreshed.session_state：模拟重新认证后的服务端登录状态；URL 仅保存非敏感会话编号。
#   - refreshed.run()：执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。
#   - next()：取迭代器的下一项；脚本模型用它取响应，页面测试用它定位匹配按钮。
#   - next(...).click()：在 AppTest 中记录一次模拟点击；随后 run 执行按钮对应的 Python 分支。
#   - next(...).click(...).run()：执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_confirmation_card_restores_after_refresh(monkeypatch, app_db):
    model = ScriptedModel(
        [
            tool_call(
                "create_ticket",
                {"product_model": "X100", "issue_description": "无法联网"},
            ),
            AIMessage(content="已创建 T9999"),
        ]
    )
    app, token = page(monkeypatch, app_db, model)
    app.chat_input[0].set_value("X100无法联网，请建单").run()
    assert not app.exception
    assert storage.list_tickets(app_db) == []
    assert any(button.label == "确认创建工单" for button in app.button)
    thread_id = sessions.list_threads("alice", app_db)[0]["thread_id"]
    refreshed = AppTest.from_file(str(storage.ROOT / "app.py"), default_timeout=30)
    refreshed.session_state["auth_token"] = token
    refreshed.query_params["thread"] = thread_id
    refreshed.run()
    assert not refreshed.exception
    next(
        button for button in refreshed.button if button.label == "确认创建工单"
    ).click().run()
    assert not refreshed.exception
    assert len(storage.list_tickets(app_db)) == 1
    assert not any(button.label == "确认创建工单" for button in refreshed.button)
    assert any(
        "T0001" in item.value and "待处理" in item.value for item in refreshed.markdown
    )


# 函数说明：test_ui_no_applicable_faq
# 功能：让模型尝试给 X100 蓝牙问题套用资料，验证页面明确显示无适用资料并保持工单表为空。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - ScriptedModel()：构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。
#   - page()：配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。
#   - app.chat_input[0].set_value()：设置测试页面控件的值；后续 run 才触发完整页面处理。
#   - app.chat_input[0].set_value(...).run()：执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_ui_no_applicable_faq(monkeypatch, app_db):
    model = ScriptedModel(
        [
            tool_call("search_faq", {"query": "X100蓝牙", "device_model": "X100"}),
            AIMessage(content="使用X200步骤"),
        ]
    )
    app, _ = page(monkeypatch, app_db, model)
    app.chat_input[0].set_value("X100蓝牙连不上").run()
    assert not app.exception
    assert any("没有找到适用于 X100" in item.value for item in app.markdown)
    assert not storage.list_tickets(app_db)


# 函数说明：test_staff_workbench_includes_customer_tickets
# 功能：先种入客户工单，再以管理员打开页面，验证工作人员能在详情选择框看到客户工单。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - storage.insert_ticket()：可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。
#   - monkeypatch.setenv()：在测试期间临时设置环境变量，例如数据库路径与模拟密钥；测试结束自动还原。
#   - auth.login()：调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - AppTest.from_file()：从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。
#   - app.run()：执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_staff_workbench_includes_customer_tickets(monkeypatch, app_db):
    with storage.connect(app_db) as db:
        storage.insert_ticket(
            db,
            {"product_model": "X100", "issue_description": "无法联网"},
            "seed",
            "alice",
        )
    monkeypatch.setenv("TICKET_DB_PATH", app_db)
    token = auth.login("admin", "test-password", app_db)["token"]
    app = AppTest.from_file(str(storage.ROOT / "app.py"), default_timeout=30)
    app.session_state["auth_token"] = token

    app.run()
    assert not app.exception
    assert any(
        item.label == "查看工单详情" and item.value == "T0001" for item in app.selectbox
    )
