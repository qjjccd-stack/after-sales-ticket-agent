"""会话恢复、结构化事实、裁剪和型号检索的边界测试。"""

import asyncio
import json
import os
import subprocess
import sys

import pytest
from conftest import new_request
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from test_graph import ScriptedModel, graph_module, run_script, tool_call

from react_agent import knowledge, sessions, storage
from react_agent.graph import trim_conversation
from react_agent.service import run_request


# 函数说明：test_explicit_facts
# 功能：对明确给出型号和故障的中文输入做参数化测试，核对结构化记忆里的 device_model 与 issue_type。
# 内部调用：
#   - sessions.extract_facts()：调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。
# 装饰器：
#   - @pytest.mark.parametrize：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
@pytest.mark.parametrize(
    "query,model,kind",
    [
        ("X100无法联网", "X100", "network"),
        ("X200 蓝牙搜索不到", "X200", "bluetooth"),
        ("X100漏电", "X100", "safety"),
    ],
)
def test_explicit_facts(query, model, kind):
    memory = sessions.extract_facts({}, query)
    assert memory["device_model"] == model and memory["issue_type"] == kind


# 函数说明：test_model_filter_and_synonyms
# 功能：核对型号隔离、蓝牙同义词、缺少型号、含糊故障和参数型号冲突，并确认来源字段可追溯。
# 内部调用：
#   - knowledge.search()：调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_model_filter_and_synonyms():
    assert knowledge.search("X100蓝牙连接不了")["matches"] == []
    assert knowledge.search("搜索不到", "X200")["matches"][0]["id"] == "FAQ-003"
    assert knowledge.search("连不上", "X200")["matches"] == []
    assert knowledge.search("联网")["error"] == "missing_model"
    assert knowledge.search("X100联网", "X200")["error"] == "model_conflict"
    entry = knowledge.search("wifi", "X100")["matches"][0]
    assert entry["source"] and entry["product_models"] == ["X100", "X200"]


# 函数说明：test_bm25_and_step_exclusion
# 功能：确认相关文档的 BM25 分数更高，并验证已尝试步骤不会再次出现在剩余步骤首位。
# 内部调用：
#   - knowledge.bm25()：调用 tokenize/Counter/log 计算 BM25；只在已经按型号过滤的资料中排序。
#   - knowledge.search()：调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_bm25_and_step_exclusion():
    scores = knowledge.bm25("配对", ["如何蓝牙配对", "怎样开机"])
    assert scores[0] > scores[1]
    outcome = knowledge.search("蓝牙", "X200", tried_steps=["FAQ-003-S1"])
    assert outcome["matches"][0]["remaining_steps"][0]["id"] == "FAQ-003-S2"


# 函数说明：test_structure_memory_survives_process
# 功能：保存两轮明确事实后启动新的 Python 进程读取同一会话，验证型号和已重启记录不依赖进程内存。
# 内部调用：
#   - new_request()：结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。
#   - subprocess.check_output()：启动新的 Python 进程并读取标准输出，验证数据持久化与重试不依赖当前内存。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
# 补充：传给子进程的 code 字符串另外调用 get_thread() 读取持久记忆，并用 json.dumps()/print() 返回 JSON；这些在新进程中执行。
def test_structure_memory_survives_process(ctx):
    new_request(ctx, "我的X100无法联网")
    new_request(ctx, "已经重启过了，还是不行")
    code = "from react_agent.sessions import get_thread; import sys,json; print(json.dumps(get_thread(sys.argv[1],sys.argv[2],sys.argv[3])['memory']))"
    output = subprocess.check_output(
        [sys.executable, "-c", code, ctx.thread_id, ctx.user_id, ctx.db_path],
        env={**os.environ, "LANGSMITH_TRACING": "false"},
    )
    memory = json.loads(output)
    assert memory["device_model"] == "X100"
    assert "重启设备" in memory["troubleshooting_steps"]


# 函数说明：test_lease_blocks_concurrent_run
# 功能：获取请求租约后再次申请执行，验证同一请求不能并发执行，也不能在租约活动时被结束。
# 内部调用：
#   - new_request()：结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。
#   - sessions.claim_request()：BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。
#   - pytest.raises()：声明代码块应抛出指定异常；未抛出或异常类型不对都会使测试失败。
#   - sessions.abandon_request()：撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_lease_blocks_concurrent_run(ctx):
    new_request(ctx)
    sessions.claim_request(ctx.request_id, ctx.user_id, ctx.db_path)
    with pytest.raises(ValueError):
        sessions.claim_request(ctx.request_id, ctx.user_id, ctx.db_path)
    assert not sessions.abandon_request(ctx.request_id, ctx.user_id, ctx.db_path)


# 函数说明：test_trim_keeps_complete_tool_pairs
# 功能：构造十二轮用户、工具请求、工具结果和回复，验证历史裁剪保留完整工具配对并符合轮数限制。
# 内部调用：
#   - range()：产生整数序列，供有界重试、模拟轮次或并发任务循环使用。
#   - HumanMessage()：构造用户消息；固定 id 可让检查点重试合并同一输入，避免重复追加。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - ToolMessage()：构造工具返回消息，通过 tool_call_id 对应模型上一条工具请求。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - messages.extend()：把另一序列的每个元素追加到列表，合并消息或分词结果。
#   - trim_conversation()：按 HumanMessage 划分完整轮次再裁剪，不拆开 AI 工具调用与 ToolMessage 配对。
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_trim_keeps_complete_tool_pairs():
    messages = []
    for i in range(12):
        messages.extend(
            [
                HumanMessage(content=f"轮次{i}"),
                tool_call("search_faq", {"query": "联网"}, str(i)),
                ToolMessage(content="{}", tool_call_id=str(i)),
                AIMessage(content="步骤"),
            ]
        )
    trimmed = trim_conversation(messages, max_chars=3000, max_turns=3)
    calls = {
        call["id"]
        for message in trimmed
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    results = {
        message.tool_call_id for message in trimmed if isinstance(message, ToolMessage)
    }
    assert calls == results
    assert isinstance(trimmed[0], HumanMessage)
    assert sum(isinstance(message, HumanMessage) for message in trimmed) <= 3


# 函数说明：test_ten_turn_conversation_memory_summary_and_no_repeated_steps
# 功能：执行十轮真实图与脚本模型对话，检查设备事实、尝试步骤、排查耗尽、早期摘要及完整可见对话，并排除模型乱编文本。
# 内部调用：
#   - range()：产生整数序列，供有界重试、模拟轮次或并发任务循环使用。
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - responses.extend()：把另一序列的每个元素追加到列表，合并消息或分词结果。
#   - ScriptedModel()：构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。
#   - monkeypatch.setattr()：在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。
#   - new_request()：结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。
#   - run_request()：验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。
#   - asyncio.run()：在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。
#   - answers.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
# 匿名函数：
#   - lambda _: model：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_ten_turn_conversation_memory_summary_and_no_repeated_steps(monkeypatch, ctx):
    responses = []
    for _ in range(10):
        responses.extend(
            [
                tool_call("search_faq", {"query": "无法联网", "device_model": "X100"}),
                AIMessage(content="乱编排查步骤"),
            ]
        )
    model = ScriptedModel(responses)
    monkeypatch.setattr(graph_module, "load_chat_model", lambda _: model)
    answers = []
    for i in range(10):
        new_request(ctx, "我的X100无法联网" if i == 0 else "已经试过了，还是不行")
        output = asyncio.run(run_request(ctx.request_id, ctx.user_id, ctx.db_path))
        assert output["success"], output
        answers.append(output["answer"])
    thread = sessions.get_thread(ctx.thread_id, ctx.user_id, ctx.db_path)
    assert thread["memory"]["device_model"] == "X100"
    assert len(thread["memory"]["troubleshooting_steps"]) >= 3
    assert "已尝试完" in answers[-1]
    assert thread["summary"] and len(thread["transcript"]) == 20
    assert "乱编" not in "".join(answers)


# 函数说明：test_model_cannot_fabricate_memory
# 功能：让模型提交用户从未说过的 X200 证据，验证记忆工具拒绝、当前 X100 不被覆盖且没有工单写入。
# 内部调用：
#   - tool_call()：构造 AIMessage 工具请求，由真实执行器校验并执行。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - sessions.timeline()：先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。
#   - event['result'].get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_model_cannot_fabricate_memory(monkeypatch, ctx):
    outcome, _ = run_script(
        monkeypatch,
        ctx,
        [
            tool_call(
                "record_ticket_context",
                {"evidence": "我的型号是X200", "device_model": "X200"},
            ),
            AIMessage(content="记住了"),
        ],
        prompt="我的是X100",
    )
    assert outcome["success"]
    events = sessions.timeline(ctx.thread_id, ctx.user_id, ctx.db_path)
    assert any(event["result"].get("error") == "unverified_fact" for event in events)
    assert (
        sessions.get_thread(ctx.thread_id, ctx.user_id, ctx.db_path)["memory"][
            "device_model"
        ]
        == "X100"
    )
    assert not storage.list_tickets(ctx.db_path)


# 函数说明：test_exhaustion_is_remembered_after_actual_step_feedback
# 功能：准备只剩最后一个可信步骤的会话，展示后接收明确失败反馈，验证耗尽状态持久保留，换型号时重置。
# 内部调用：
#   - sessions.TicketContext()：按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。
#   - sessions.TicketContext(...).model_dump()：把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。
#   - knowledge.search()：调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。
#   - render_faq()：用可信 FAQ 返回值选择一个新步骤并引用来源；调用方负责保存 last_suggested_step。
#   - sessions.save_memory()：用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - sessions.extract_facts()：调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_exhaustion_is_remembered_after_actual_step_feedback(monkeypatch, ctx):
    from react_agent.graph import render_faq

    memory = sessions.TicketContext(
        device_model="X100",
        issue_type="network",
        issue_description="无法联网",
        troubleshooting_steps=["FAQ-001-S1", "FAQ-001-S2", "FAQ-001-S3"],
    ).model_dump()
    outcome = knowledge.search(
        "联网", "X100", tried_steps=memory["troubleshooting_steps"]
    )
    render_faq(outcome, memory)
    assert not memory["diagnosis_exhausted"]
    sessions.save_memory(ctx.thread_id, ctx.user_id, memory, ctx.db_path)
    result, _ = run_script(
        monkeypatch,
        ctx,
        [AIMessage(content="全部试完，可以建单")],
        "已经试过了，还是不行",
    )
    assert "可靠排查步骤已尝试完" in result["answer"]
    changed = sessions.extract_facts(
        sessions.get_thread(ctx.thread_id, ctx.user_id, ctx.db_path)["memory"],
        "换成X200蓝牙连接失败",
    )
    assert not changed["diagnosis_exhausted"]


# 函数说明：test_checkpoint_keeps_only_trusted_final_text
# 功能：先让模型生成虚构退款文字，再发下一轮消息，检查模型看到的历史只包含应用实际展示的可信回复。
# 内部调用：
#   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
#   - run_script()：替换模型后通过 service.run_request 运行真实检查点与请求生命周期。
#   - getattr()：读取属性并允许指定缺省值，兼容字典之外的消息对象。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_checkpoint_keeps_only_trusted_final_text(monkeypatch, ctx):
    run_script(monkeypatch, ctx, [AIMessage(content="虚构退款成功")], "我的是X100")
    result, model = run_script(
        monkeypatch, ctx, [AIMessage(content="再次虚构")], "型号是什么"
    )
    assert result["success"]
    texts = [getattr(message, "content", "") for message in model.inputs[0]]
    assert not any("虚构退款成功" in str(text) for text in texts)
    assert any("已记录设备型号 X100" in str(text) for text in texts)
