"""模型可调用的查询/提案工具。确认执行不在 TOOLS 中。"""

from langgraph.runtime import get_runtime

from react_agent import actions, knowledge, sessions, storage
from react_agent.context import Context


# 函数说明：search_faq
# 功能：按确切型号、故障类别检索本地 FAQ，返回来源和未尝试步骤；无型号先追问，无匹配不能编造。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - memory.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - device_model.upper()：把字母转为大写，统一设备型号或错误码。
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - knowledge.search()：调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。
def search_faq(
    query: str, device_model: str | None = None, issue_type: str | None = None
) -> dict:
    """按确切型号、故障类别检索本地 FAQ，返回来源和未尝试步骤；无型号先追问，无匹配不能编造。"""
    context = get_runtime(Context).context
    memory = sessions.get_thread(context.thread_id, context.user_id, context.db_path)[
        "memory"
    ]
    known_model = memory.get("device_model")
    # 已从用户原文确认的型号不允许模型换成另一型号来绕过资料过滤。
    if known_model and device_model and device_model.upper() != known_model:
        return storage.result(
            "search_faq",
            False,
            "model_conflict",
            "检索型号与用户已提供的型号不同。",
            matches=[],
        )
    if issue_type and memory.get("issue_type") not in {None, "other", issue_type}:
        return storage.result(
            "search_faq",
            False,
            "issue_conflict",
            "检索故障类别与当前记录不同，请核对故障。",
            matches=[],
        )
    return knowledge.search(
        query,
        known_model or device_model,
        issue_type or memory.get("issue_type"),
        memory["troubleshooting_steps"],
    )


# 函数说明：create_ticket
# 功能：提出建单确认卡片（不会写工单）；impact 为 single/multiple/all，必填型号和用户原始故障描述。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
# 补充：注意同名函数：这里是模型工具，只提出卡片；storage.create_ticket 是可信内部兼容入口，未暴露给模型。
def create_ticket(
    product_model: str = "", issue_description: str = "", impact: str = "single"
) -> dict:
    """提出建单确认卡片（不会写工单）；impact 为 single/multiple/all，必填型号和用户原始故障描述。"""
    context = get_runtime(Context).context
    return actions.propose(
        context,
        "create_ticket",
        {
            "product_model": product_model,
            "issue_description": issue_description,
            "impact": impact,
        },
    )


# 函数说明：get_ticket_status
# 功能：按权限查询真实工单和处理历史；编号只能来自用户输入或已查询到的真实记录。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.read_ticket()：调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。
def get_ticket_status(ticket_id: str) -> dict:
    """按权限查询真实工单和处理历史；编号只能来自用户输入或已查询到的真实记录。"""
    return actions.read_ticket(get_runtime(Context).context, ticket_id, history=True)


# 函数说明：search_tickets
# 功能：按编号、型号、状态及 YYYY-MM-DD 起止日期查找工单；客户始终只能查自己的历史工单。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.search_tickets()：按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。
def search_tickets(
    ticket_id: str = "",
    product_model: str = "",
    status: str = "",
    created_from: str = "",
    created_to: str = "",
    mine: bool = True,
) -> dict:
    """按编号、型号、状态及 YYYY-MM-DD 起止日期查找工单；客户始终只能查自己的历史工单。"""
    return actions.search_tickets(
        get_runtime(Context).context,
        ticket_id,
        product_model,
        status,
        created_from,
        created_to,
        mine,
    )


# 函数说明：update_ticket_status
# 功能：提出工单状态流转；检查当前状态与权限，需用户点击确认后生效。处理人来自应用身份。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
def update_ticket_status(ticket_id: str, new_status: str, note: str) -> dict:
    """提出工单状态流转；检查当前状态与权限，需用户点击确认后生效。处理人来自应用身份。"""
    return actions.propose(
        get_runtime(Context).context,
        "update_ticket_status",
        {"ticket_id": ticket_id, "new_status": new_status, "note": note},
    )


# 函数说明：supplement_ticket
# 功能：提出补充故障描述、联系方式或设备信息；不覆盖原始故障，确认后追加并记录审计。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
def supplement_ticket(
    ticket_id: str, description: str = "", contact: str = "", device_info: str = ""
) -> dict:
    """提出补充故障描述、联系方式或设备信息；不覆盖原始故障，确认后追加并记录审计。"""
    return actions.propose(
        get_runtime(Context).context,
        "supplement_ticket",
        {
            "ticket_id": ticket_id,
            "description": description,
            "contact": contact,
            "device_info": device_info,
        },
    )


# 函数说明：cancel_ticket
# 功能：提出取消尚在待处理的工单；已开始维修不可取消，需页面确认。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
def cancel_ticket(ticket_id: str, note: str = "用户申请取消") -> dict:
    """提出取消尚在待处理的工单；已开始维修不可取消，需页面确认。"""
    return actions.propose(
        get_runtime(Context).context,
        "cancel_ticket",
        {"ticket_id": ticket_id, "note": note},
    )


# 函数说明：assign_ticket
# 功能：客服/管理员提出分派给已有维修账号；建单时也会按型号、故障专长和负载自动推荐人员。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
def assign_ticket(ticket_id: str, assignee_id: str) -> dict:
    """客服/管理员提出分派给已有维修账号；建单时也会按型号、故障专长和负载自动推荐人员。"""
    return actions.propose(
        get_runtime(Context).context,
        "assign_ticket",
        {"ticket_id": ticket_id, "assignee_id": assignee_id},
    )


# 函数说明：set_ticket_priority
# 功能：客服/管理员提出将优先级调整为普通、高、紧急之一，需要确认并保留处理说明。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
def set_ticket_priority(
    ticket_id: str, priority: str, note: str = "调整紧急程度"
) -> dict:
    """客服/管理员提出将优先级调整为普通、高、紧急之一，需要确认并保留处理说明。"""
    return actions.propose(
        get_runtime(Context).context,
        "set_ticket_priority",
        {"ticket_id": ticket_id, "priority": priority, "note": note},
    )


# 函数说明：handoff_ticket
# 功能：现有工单申请人工接管并保存原因；没有工单时先建议用户确认建单。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
def handoff_ticket(ticket_id: str, note: str) -> dict:
    """现有工单申请人工接管并保存原因；没有工单时先建议用户确认建单。"""
    return actions.propose(
        get_runtime(Context).context,
        "handoff_ticket",
        {"ticket_id": ticket_id, "note": note},
    )


# 函数说明：record_ticket_context
# 功能：以用户原文 evidence 保存型号/故障/已尝试步骤；字段必须出现在证据中，不接受推断出的工单编号或权限。
# 内部调用：
#   - get_runtime()：读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - value.casefold()：进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。
#   - evidence.casefold()：进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。
#   - device_model.upper()：把字母转为大写，统一设备型号或错误码。
#   - knowledge.classify_issue()：按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。
#   - dict.fromkeys()：用字典键的唯一性去重并保留首次出现顺序，随后可转回列表。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
#   - sessions.save_memory()：用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。
def record_ticket_context(
    evidence: str,
    device_model: str = "",
    issue_description: str = "",
    tried_step: str = "",
) -> dict:
    """以用户原文 evidence 保存型号/故障/已尝试步骤；字段必须出现在证据中，不接受推断出的工单编号或权限。"""
    context = get_runtime(Context).context
    thread = sessions.get_thread(context.thread_id, context.user_id, context.db_path)
    statements = [
        item["content"] for item in thread["transcript"] if item["role"] == "user"
    ]
    if (
        not evidence
        or not any(evidence in text for text in statements)
        or len(evidence) > 2000
    ):
        return storage.result(
            "record_ticket_context",
            False,
            "unverified_fact",
            "记忆必须引用用户说过的原文。",
        )
    for value in (device_model, issue_description, tried_step):
        if value and value.casefold() not in evidence.casefold():
            return storage.result(
                "record_ticket_context",
                False,
                "unverified_fact",
                "字段不在用户提供的证据中。",
            )
    memory = thread["memory"]
    if device_model:
        if memory["device_model"] and device_model.upper() != memory["device_model"]:
            return storage.result(
                "record_ticket_context",
                False,
                "model_conflict",
                "不能用旧证据覆盖当前型号。",
            )
        memory["device_model"] = device_model.upper()
    if issue_description:
        memory["issue_description"] = issue_description
        memory["issue_type"] = knowledge.classify_issue(issue_description)
    if tried_step:
        memory["troubleshooting_steps"] = list(
            dict.fromkeys([*memory["troubleshooting_steps"], tried_step])
        )[-40:]
    sessions.save_memory(context.thread_id, context.user_id, memory, context.db_path)
    return storage.result("record_ticket_context", memory=memory)


TOOLS = [
    search_faq,
    create_ticket,
    get_ticket_status,
    search_tickets,
    update_ticket_status,
    supplement_ticket,
    cancel_ticket,
    assign_ticket,
    set_ticket_priority,
    handoff_ticket,
    record_ticket_context,
]
