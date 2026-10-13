"""LangGraph 会话状态：消息由 add_messages 合并，业务事实也保存到 SQLite 会话表。"""

from dataclasses import dataclass, field
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from react_agent.sessions import TicketContext


# 数据类说明：@dataclass 自动生成初始化方法，没有手写业务函数。
# field(default_factory=list) 每次构造一个新的消息列表，避免不同状态共用列表。
# Annotated 中的 add_messages 是交给 LangGraph 的合并回调：按消息 ID 添加或替换消息。
@dataclass
class InputState:
    """请求输入；固定消息 ID 让失败重试不会重复追加同一条用户消息。"""

    messages: Annotated[list[AnyMessage], add_messages] = field(default_factory=list)


# 数据类说明：State 继承 InputState 的消息字段，并增加本轮请求与业务事实。
# ticket_context 的 lambda 在创建状态时调用 TicketContext() 校验默认字段，
# 再调用 model_dump() 转成独立字典；facts 的 list 工厂同样防止共享可变默认值。
@dataclass
class State(InputState):
    """保存请求 ID、结构化事实和最终可信回复；这些字段均随检查点持久化。"""

    request_id: str = ""
    ticket_context: dict = field(default_factory=lambda: TicketContext().model_dump())
    summary: str = ""
    final_answer: str = ""
    facts: list[dict] = field(default_factory=list)
