"""Text extraction and configurable model loading."""

import json

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage


# 函数说明：get_message_text
# 功能：从模型或工具消息中提取文本，统一处理字符串内容和内容块列表。
# 内部调用：
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - c.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
def get_message_text(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    return "".join(c if isinstance(c, str) else c.get("text", "") for c in content)


# 函数说明：get_tool_result
# 功能：把工具消息还原为 Python 数据：空列表仍返回空列表，合法 JSON 解码为结构化对象，普通文本包装为 message 字段。
# 内部调用：
#   - get_message_text()：从模型或工具消息中提取文本，统一处理字符串内容和内容块列表。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
def get_tool_result(msg: ToolMessage):
    """Preserve the empty list that ToolNode emits for an unmatched FAQ."""
    if msg.content == []:
        return []
    content = get_message_text(msg)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"message": content}


# 函数说明：load_chat_model
# 功能：按 provider/model 配置创建支持工具调用的聊天模型客户端；创建对象时不发起本轮模型推理。
# 内部调用：
#   - fully_specified_name.split()：按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。
#   - ValueError()：构造无效参数或状态异常，交给调用方捕获和显示。
#   - init_chat_model()：根据 provider/model 创建聊天模型客户端并设置温度、超时和 SDK 重试参数；创建客户端本身不等于发起推理。
def load_chat_model(fully_specified_name: str) -> BaseChatModel:
    provider, model = fully_specified_name.split("/", maxsplit=1)
    if provider not in {"deepseek", "openai"}:
        raise ValueError("MODEL 只支持 deepseek/模型名 或 openai/模型名。")
    return init_chat_model(
        model, model_provider=provider, temperature=0, timeout=45, max_retries=0
    )
