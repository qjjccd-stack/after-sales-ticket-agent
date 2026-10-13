"""应用执行入口：认证用户、稳定请求 ID、SQLite 检查点、恢复和用量统计。"""

import asyncio
import os
import time

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from react_agent import auth, sessions, storage
from react_agent.context import Context
from react_agent.graph import build_graph


# 函数说明：usage_for
# 功能：从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。
# 内部调用：
#   - usage.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
#   - starts.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
#   - row.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
def usage_for(events):
    """从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。"""
    starts = {
        row["args"]["attempt_id"]: row for row in events if row["kind"] == "model_start"
    }
    usage = {
        row["args"]["attempt_id"]: row["result"]
        for row in events
        if row["kind"] == "model_usage"
    }
    measured = list(usage.values())
    missing = [
        row["result"]["reserved_tokens"]
        for key, row in starts.items()
        if key not in usage
    ]
    return {
        "model_calls": len(starts),
        "tool_calls": sum(row["kind"] == "tool_start" for row in events),
        "input_tokens": sum(row.get("input_tokens", 0) for row in measured),
        "output_tokens": sum(row.get("output_tokens", 0) for row in measured),
        "total_tokens": sum(row.get("total_tokens", 0) for row in measured)
        + sum(missing),
        "estimated_tokens": bool(missing)
        or any(row.get("estimated") for row in measured),
        "model_elapsed_ms": sum(
            row["elapsed_ms"] for row in events if row["kind"] == "model_usage"
        ),
    }


# 函数说明：monetary_cost
# 功能：仅在应用设置每百万 token 单价时计算估算成本；不把未知价格写成零。
# 内部调用：
#   - float()：把配置的单价文本转换为浮点数，转换失败交给异常分支处理。
#   - round()：按指定小数位四舍五入，使相似度、费用或耗时便于展示。
def monetary_cost(usage):
    """仅在应用设置每百万 token 单价时计算估算成本；不把未知价格写成零。"""
    try:
        input_price = float(os.environ["INPUT_PRICE_PER_MILLION"])
        output_price = float(os.environ["OUTPUT_PRICE_PER_MILLION"])
    except (KeyError, ValueError):
        return None
    return round(
        (usage["input_tokens"] * input_price + usage["output_tokens"] * output_price)
        / 1_000_000,
        6,
    )


# 函数说明：run_request
# 功能：验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。
# 内部调用：
#   - auth.get_user()：调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。
#   - PermissionError()：构造身份或资源归属校验失败的异常，阻止后续操作。
#   - sessions.get_request()：按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。
#   - sessions.claim_request()：BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
#   - sessions.timeline()：先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。
#   - usage_for()：从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。
#   - time.monotonic()：读取单调递增时间，计算耗时，不受系统日期调整影响。
#   - storage.database_path()：调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - AsyncSqliteSaver.from_conn_string()：打开官方异步 SQLite 检查点管理器，保存/恢复图状态；async with 结束时释放连接。
#   - build_graph()：用 StateGraph 装配模型—工具循环；传入官方 AsyncSqliteSaver 后支持跨进程恢复。
#   - agent.aget_state()：读取 thread_id 对应的最新图状态及待执行节点，判断应开始新轮次、续跑还是复用完成结果。
#   - snapshot.values.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - HumanMessage()：构造用户消息；固定 id 可让检查点重试合并同一输入，避免重复追加。
#   - asyncio.timeout()：为整个异步代码块设置总时间限制，避免单轮 Agent 长期不结束。
#   - agent.astream()：真正执行或恢复状态图，按节点更新流返回消息和最终结果。
#   - update.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - node.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - messages.extend()：把另一序列的每个元素追加到列表，合并消息或分词结果。
#   - message.model_dump()：把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。
#   - round()：按指定小数位四舍五入，使相似度、费用或耗时便于展示。
#   - monetary_cost()：仅在应用设置每百万 token 单价时计算估算成本；不把未知价格写成零。
#   - sessions.finish_request()：校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。
#   - type()：取得对象的类型；此处主要用异常类型名记录错误类别。
async def run_request(request_id, user_id, db_path=None, **limits):
    """claim_request 获取租约，用 aget_state 判断是否恢复检查点，astream 收集输出，finish_request 保存结果。"""
    if not auth.get_user(user_id, db_path):
        raise PermissionError("请重新登录")
    request = sessions.get_request(request_id, user_id, db_path)
    if request["status"] == "done":
        return request["output"]
    token = sessions.claim_request(request_id, user_id, db_path)
    if token is None:
        return request["output"]
    context = Context(
        request_id=request_id,
        thread_id=request["thread_id"],
        user_id=user_id,
        db_path=db_path,
        **limits,
    )
    previous = [
        event
        for event in sessions.timeline(context.thread_id, user_id, db_path)
        if event["request_id"] == request_id
    ]
    usage = usage_for(previous)
    context.model_calls, context.tool_calls, context.tokens = (
        usage["model_calls"],
        usage["tool_calls"],
        usage["total_tokens"],
    )
    context.input_tokens, context.output_tokens = (
        usage["input_tokens"],
        usage["output_tokens"],
    )
    context.estimated_tokens = usage["estimated_tokens"]
    started, messages = time.monotonic(), []
    config = {"configurable": {"thread_id": context.thread_id}, "recursion_limit": 24}
    try:
        async with AsyncSqliteSaver.from_conn_string(
            str(storage.database_path(db_path))
        ) as checkpointer:
            agent = build_graph(checkpointer)
            snapshot = await agent.aget_state(config)
            if (
                snapshot.values.get("request_id") == request_id
                and snapshot.values.get("final_answer")
                and not snapshot.next
            ):
                answer = snapshot.values["final_answer"]
            else:
                resume = snapshot.values.get("request_id") == request_id and bool(
                    snapshot.next
                )
                input_state = (
                    None
                    if resume
                    else {
                        "messages": [
                            HumanMessage(
                                content=request["input"], id=f"user-{request_id}"
                            )
                        ]
                    }
                )
                async with asyncio.timeout(context.execution_timeout):
                    async for update in agent.astream(
                        input_state,
                        context=context,
                        config=config,
                        stream_mode="updates",
                    ):
                        for node in update.values():
                            messages.extend(
                                message
                                for message in node.get("messages", [])
                                if message.type != "remove"
                            )
                state = await agent.aget_state(config)
                answer = state.values["final_answer"]
        events = [
            row
            for row in sessions.timeline(context.thread_id, user_id, db_path)
            if row["request_id"] == request_id
        ]
        usage = usage_for(events)
        outcome = {
            "success": True,
            "answer": answer,
            "request_id": request_id,
            "thread_id": context.thread_id,
            "messages": [message.model_dump(mode="json") for message in messages],
            "usage": usage,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "cost_estimate": monetary_cost(usage),
        }
        sessions.finish_request(request_id, user_id, token, outcome, db_path)
        return outcome
    except Exception as error:
        events = [
            row
            for row in sessions.timeline(context.thread_id, user_id, db_path)
            if row["request_id"] == request_id
        ]
        usage = usage_for(events)
        outcome = {
            "success": False,
            "answer": "本次执行未完成，可以重试原请求。尚未确认的操作不会写入工单。",
            "error_code": type(error).__name__,
            "request_id": request_id,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "usage": usage,
            "cost_estimate": monetary_cost(usage),
        }
        sessions.finish_request(
            request_id, user_id, token, outcome, db_path, failed=True
        )
        return outcome
