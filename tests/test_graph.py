"""脚本化模型驱动真实图、工具、SQLite；这些测试不代表真实模型自主决策效果。"""

import asyncio
import importlib

from conftest import new_request
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from react_agent import actions, sessions, storage
from react_agent.service import run_request
from react_agent.tools import TOOLS

graph_module = importlib.import_module("react_agent.graph")


class ScriptedModel:
    """按顺序返回预设消息，记录输入以检查工具返回值和裁剪策略。"""

    # 函数说明：ScriptedModel.__init__
    # 功能：调用 iter 保存预设序列。
    # 内部调用：
    #   - iter()：把固定响应列表转成迭代器，让脚本模型逐条返回消息。
    def __init__(self, responses):
        """调用 iter 保存预设序列。"""
        self.responses = iter(responses)
        self.inputs = []

    # 函数说明：ScriptedModel.bind_tools
    # 功能：模拟工具绑定，不执行工具；返回自身。
    # 内部调用：
    #   - 无；本函数仅比较字段、返回固定值或返回对象本身。
    def bind_tools(self, tools):
        """模拟工具绑定，不执行工具；返回自身。"""
        return self

    # 函数说明：ScriptedModel.ainvoke
    # 功能：记录模型输入，再 next 返回预设结果或抛出预设异常。
    # 内部调用：
    #   - self.inputs.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
    #   - next()：取迭代器的下一项；脚本模型用它取响应，页面测试用它定位匹配按钮。
    #   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
    async def ainvoke(self, messages):
        """记录模型输入，再 next 返回预设结果或抛出预设异常。"""
        self.inputs.append(messages)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


# 函数说明：tool_call
# 功能：构造 AIMessage 工具请求，由真实执行器校验并执行。
# 内部调用：
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
def tool_call(name, args, call_id="call-1"):
    """构造 AIMessage 工具请求，由真实执行器校验并执行。"""
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


# 函数说明：run_script
# 功能：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
# 内部调用：
#   - ScriptedModel()：构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。
#   - monkeypatch.setattr()：在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。
#   - new_request()：结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。
#   - run_request()：验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。
#   - asyncio.run()：在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。
# 匿名函数：
#   - lambda _: model：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。
def run_script(
    monkeypatch, ctx, responses, prompt="X100无法联网，请帮我建单", **limits
):
    """替换模型后通过 service.run_request 运行真实检查点与请求生命周期。"""
    model = ScriptedModel(responses)
    monkeypatch.setattr(graph_module, "load_chat_model", lambda _: model)
    new_request(ctx, prompt)
    result = asyncio.run(
        run_request(ctx.request_id, ctx.user_id, ctx.db_path, **limits)
    )
    return result, model


# 函数说明：test_identity_and_confirmation_are_not_model_parameters
# 功能：把所有模型工具转成真实 schema，确认没有确认执行工具，也没有角色、用户、请求号或 confirmed 等可信应用字段。
# 内部调用：
#   - convert_to_openai_tool()：把 Python 工具转换成模型可见的工具 schema，测试据此检查是否泄露可信参数。
#   - schemas.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - set()：构造不重复元素集合，用于检查未知参数、工具配对或唯一查询词。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_identity_and_confirmation_are_not_model_parameters():
    schemas = {
        convert_to_openai_tool(tool)["function"]["name"]: convert_to_openai_tool(tool)[
            "function"
        ]["parameters"]["properties"]
        for tool in TOOLS
    }
    assert "confirm_action" not in schemas
    for schema in schemas.values():
        assert not {
            "confirmed",
            "operator_id",
            "user_id",
            "role",
            "request_id",
            "db_path",
        } & set(schema)


# 函数说明：test_proposal_never_writes_until_click_and_model_receives_result
# 功能：让脚本模型提出建单并谎称成功，验证工具结果已交回模型、页面显示尚未执行、数据库在显式确认前为空。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_proposal_never_writes_until_click_and_model_receives_result(monkeypatch, ctx):
    result, model = run_script(
        monkeypatch,
        ctx,
        [
            tool_call(
                "create_ticket",
                {"product_model": "X100", "issue_description": "无法联网"},
            ),
            AIMessage(content="工单已经创建成功"),
        ],
    )
    assert result["success"]
    assert "尚未执行" in result["answer"]
    assert "awaiting_confirmation" in model.inputs[1][-1].content
    assert storage.list_tickets(ctx.db_path) == []
    pending = actions.pending_actions(ctx)
    assert len(pending) == 1
    saved = actions.confirm_action(ctx, pending[0]["operation_id"])
    assert saved["success"] and saved["ticket"]["status"] == "待处理"


# 函数说明：test_prohibited_operation_denied_even_if_model_calls_tool
# 功能：用户明确禁止建单时仍让脚本模型请求建单，验证执行层拒绝提案和写入。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_prohibited_operation_denied_even_if_model_calls_tool(monkeypatch, ctx):
    result, _ = run_script(
        monkeypatch,
        ctx,
        [
            tool_call(
                "create_ticket",
                {"product_model": "X100", "issue_description": "无法联网"},
            ),
            AIMessage(content="创建成功"),
        ],
        "X100无法联网，禁止创建工单",
    )
    assert result["success"]
    assert "OPERATION_DENIED" in result["answer"]
    assert actions.pending_actions(ctx) == []
    assert storage.list_tickets(ctx.db_path) == []


# 函数说明：test_model_cannot_supply_confirmed_or_call_confirmation
# 功能：模拟额外 confirmed 参数及不存在的 confirm_action 模型工具，验证两种绕过确认的方式都无效。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_model_cannot_supply_confirmed_or_call_confirmation(monkeypatch, ctx):
    result, _ = run_script(
        monkeypatch,
        ctx,
        [
            tool_call(
                "create_ticket",
                {
                    "product_model": "X100",
                    "issue_description": "无法联网",
                    "confirmed": True,
                },
            ),
            AIMessage(content="创建成功"),
        ],
    )
    assert "INVALID_FIELDS" in result["answer"]
    assert not actions.pending_actions(ctx)
    result, _ = run_script(
        monkeypatch,
        ctx,
        [
            tool_call("confirm_action", {"operation_id": "fake"}),
            AIMessage(content="已解决"),
        ],
    )
    assert "已解决" not in result["answer"]
    assert storage.list_tickets(ctx.db_path) == []


# 函数说明：test_no_tool_fabricated_status_is_not_displayed
# 功能：模型未取得工具证据却声称已解决和退款，验证应用最终回复不会展示这些未经验证的陈述。
# 内部调用：
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_no_tool_fabricated_status_is_not_displayed(monkeypatch, ctx):
    result, _ = run_script(
        monkeypatch,
        ctx,
        [AIMessage(content="T0001已经修改为已解决，完成退款。")],
        "T0001修好了么",
    )
    assert "已解决" not in result["answer"]
    assert "退款" not in result["answer"]


# 函数说明：test_faq_wrong_model_cannot_bypass_filter
# 功能：用户已明确 X100 时让模型检索 X200，验证型号冲突被工具层拒绝，错误教程不会显示。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_faq_wrong_model_cannot_bypass_filter(monkeypatch, ctx):
    result, _ = run_script(
        monkeypatch,
        ctx,
        [
            tool_call("search_faq", {"query": "蓝牙", "device_model": "X200"}),
            AIMessage(content="请按X200教程操作"),
        ],
        "X100蓝牙连不上",
    )
    assert "型号不同" in result["answer"]
    assert "教程" not in result["answer"]


# 函数说明：test_tool_budget_stops_before_extra_execution
# 功能：让模型一次请求五次建单、只允许一次工具执行，验证只保存一个提案并且没有实际工单。
# 内部调用：
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - range()：产生整数序列，供有界重试、模拟轮次或并发任务循环使用。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_tool_budget_stops_before_extra_execution(monkeypatch, ctx):
    calls = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "create_ticket",
                "args": {"product_model": "X100", "issue_description": "无法联网"},
                "id": str(i),
            }
            for i in range(5)
        ],
    )
    result, _ = run_script(monkeypatch, ctx, [calls], max_tool_calls=1)
    assert result["usage"]["tool_calls"] == 1
    assert len(actions.pending_actions(ctx)) == 1
    assert not storage.list_tickets(ctx.db_path)


# 函数说明：test_token_budget_prevents_model_call
# 功能：把 token 预算设为 1，验证预检在调用模型前终止，也不产生待确认操作。
# 内部调用：
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_token_budget_prevents_model_call(monkeypatch, ctx):
    result, model = run_script(monkeypatch, ctx, [], max_tokens=1)
    assert result["success"]
    assert not model.inputs
    assert not actions.pending_actions(ctx)


# 函数说明：test_sqlite_checkpoint_resume_does_not_repeat_tool
# 功能：在提案成功后的模型阶段注入异常，再重试原请求，验证从检查点继续、工具不重复执行、请求最终完成。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - RuntimeError()：构造执行/协议异常；测试中也用于模拟中断，不是业务成功结果。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - ScriptedModel()：构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。
#   - monkeypatch.setattr()：在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。
#   - run_request()：验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。
#   - asyncio.run()：在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。
#   - sessions.get_request()：按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。
# 匿名函数：
#   - lambda _: model：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_sqlite_checkpoint_resume_does_not_repeat_tool(monkeypatch, ctx):
    result, _ = run_script(
        monkeypatch,
        ctx,
        [
            tool_call(
                "create_ticket",
                {"product_model": "X100", "issue_description": "无法联网"},
            ),
            RuntimeError("simulated interruption"),
        ],
    )
    assert not result["success"]
    request_id = ctx.request_id
    assert len(actions.pending_actions(ctx)) == 1
    model = ScriptedModel([AIMessage(content="请确认")])
    monkeypatch.setattr(graph_module, "load_chat_model", lambda _: model)
    resumed = asyncio.run(run_request(request_id, ctx.user_id, ctx.db_path))
    assert resumed["success"] and "尚未执行" in resumed["answer"]
    assert len(actions.pending_actions(ctx)) == 1
    assert resumed["usage"]["tool_calls"] == 1
    assert (
        sessions.get_request(request_id, ctx.user_id, ctx.db_path)["status"] == "done"
    )


# 函数说明：test_transient_model_timeout_retried_with_accounted_budget
# 功能：先注入一次模型超时再返回有效提案，验证仅有界重试、累计模型调用和估算用量均保留，且不自动写工单。
# 内部调用：
#   - TimeoutError()：构造超时异常；此处测试用它模拟可重试的模型请求失败。
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_transient_model_timeout_retried_with_accounted_budget(monkeypatch, ctx):
    outcome, model = run_script(
        monkeypatch,
        ctx,
        [
            TimeoutError("offline"),
            tool_call(
                "create_ticket",
                {"product_model": "X100", "issue_description": "无法联网"},
            ),
            AIMessage(content="成功"),
        ],
    )
    assert outcome["success"]
    assert outcome["usage"]["model_calls"] == 3
    assert outcome["usage"]["estimated_tokens"]
    assert len(model.inputs) == 3
    assert not storage.list_tickets(ctx.db_path)
