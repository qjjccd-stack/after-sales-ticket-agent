"""应用注入身份、请求和执行预算；这些字段不出现在模型的工具参数中。"""

import os
from dataclasses import dataclass, field

from react_agent.prompts import SYSTEM_PROMPT


# 数据类说明：Context 没有手写 __init__，@dataclass 自动生成关键字参数构造方法。
# field(default_factory=...) 接收一个工厂函数；创建每个 Context 时才执行工厂。
# 下方 lambda 调用 os.getenv() 读取 MODEL，未配置时返回默认模型名。
# user_id/thread_id/request_id 由应用注入，不是模型可以填写的工具参数。
@dataclass(kw_only=True)
class Context:
    """由服务层构造；field 为每次运行建立独立配置，身份由登录记录恢复。"""

    system_prompt: str = SYSTEM_PROMPT
    model: str = field(
        default_factory=lambda: os.getenv("MODEL", "deepseek/deepseek-chat")
    )
    request_id: str = ""
    thread_id: str = ""
    user_id: str = ""
    db_path: str | None = None
    max_model_calls: int = 4
    max_tool_calls: int = 8
    max_tokens: int = 16000
    max_input_chars: int = 12000
    max_output_tokens: int = 900
    model_timeout: float = 35
    execution_timeout: float = 100
    # 由持久执行日志初始化，因此刷新/失败重试不会把累计预算重置。
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_tokens: bool = False
