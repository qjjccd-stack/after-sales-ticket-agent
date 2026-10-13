"""Minimal live model -> local tool -> model check; exits 2 without credentials."""

import asyncio
import json
import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage

from react_agent.context import Context
from react_agent.knowledge import search
from react_agent.storage import ROOT
from react_agent.tools import search_faq
from react_agent.utils import get_message_text, load_chat_model


# 函数说明：main
# 功能：做最小真实连接验收：强制模型选择 FAQ 工具，在本地执行工具，再让模型根据结果回答。
# 内部调用：
#   - load_dotenv()：从 .env 加载配置到进程环境，默认不覆盖已经存在的环境变量。
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
#   - context.model.startswith()：判断文本是否带指定前缀；此处按模型提供商选择需要读取的密钥。
#   - os.getenv()：读取环境变量，可指定默认值；读取的是当前进程配置。
#   - os.getenv(...).strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - print()：向终端输出评测进度、证据或结果，便于观察脚本执行情况。
#   - load_chat_model()：按 provider/model 配置创建支持工具调用的聊天模型客户端；创建对象时不发起本轮模型推理。
#   - HumanMessage()：构造用户消息；固定 id 可让检查点重试合并同一输入，避免重复追加。
#   - model.bind_tools()：把工具的名称、说明和参数 schema 绑定给模型；真实工具执行仍由 execute_tools 完成。
#   - model.bind_tools(...).ainvoke()：异步调用已配置的模型，返回助手文本或工具请求；测试模型则返回预设响应。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - RuntimeError()：构造执行/协议异常；测试中也用于模拟中断，不是业务成功结果。
#   - search()：调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。
#   - result.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - json.dumps()：把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。
#   - ToolMessage()：构造工具返回消息，通过 tool_call_id 对应模型上一条工具请求。
#   - model.ainvoke()：异步调用已配置的模型，返回助手文本或工具请求；测试模型则返回预设响应。
#   - get_message_text()：从模型或工具消息中提取文本，统一处理字符串内容和内容块列表。
#   - get_message_text(...).strip()：去除文本两端空白，规范输入或判断是否只含空白。
async def main() -> int:
    load_dotenv(ROOT / ".env")
    context = Context()
    key = (
        "DEEPSEEK_API_KEY"
        if context.model.startswith("deepseek/")
        else "OPENAI_API_KEY"
    )
    if not os.getenv(key, "").strip():
        print(f"NOT RUN：请先在 .env 配置 {key}。没有调用真实模型。")
        return 2
    model = load_chat_model(context.model)
    prompt = HumanMessage(content="请查询本地 FAQ：X100 无法联网，给出排查步骤。")
    response = await model.bind_tools([search_faq], tool_choice="search_faq").ainvoke(
        [prompt]
    )
    if len(response.tool_calls) != 1 or response.tool_calls[0]["name"] != "search_faq":
        raise RuntimeError("模型未返回预期的工具调用")
    call = response.tool_calls[0]
    result = search(**call["args"])
    if not result.get("matches"):
        raise RuntimeError("模型参数没有匹配本地 FAQ")
    print(json.dumps({"tool": call, "result": result}, ensure_ascii=False, indent=2))
    answer = await model.ainvoke(
        [
            prompt,
            response,
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]
            ),
        ]
    )
    if not get_message_text(answer).strip():
        raise RuntimeError("模型最终回复为空")
    print(get_message_text(answer))
    print("PASS：模型工具调用与本地 FAQ 已连通；答案是否忠实仍需人工核对。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"FAIL：{type(exc).__name__}。请检查模型配置、网络和额度。")
        raise SystemExit(1) from None
