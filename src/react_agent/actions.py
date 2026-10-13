"""有限状态机、权限和双阶段写入。模型只能 propose；confirm_action 仅由页面按钮调用。"""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from uuid import uuid4

from react_agent import knowledge, sessions, storage

WRITE_ACTIONS = {
    "create_ticket",
    "update_ticket_status",
    "supplement_ticket",
    "cancel_ticket",
    "assign_ticket",
    "set_ticket_priority",
    "handoff_ticket",
}
TRANSITIONS = {
    "待处理": {"处理中", "已关闭"},
    "处理中": {"待用户确认"},
    "待用户确认": {"处理中", "已解决"},
    "已解决": {"已关闭"},
    "已关闭": set(),
}
ACTION_LABELS = {
    "create_ticket": "创建工单",
    "update_ticket_status": "变更状态",
    "supplement_ticket": "补充信息",
    "cancel_ticket": "取消工单",
    "assign_ticket": "分派工单",
    "set_ticket_priority": "调整优先级",
    "handoff_ticket": "转人工",
}


# 函数说明：actor_in
# 功能：查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。
# 内部调用：
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - PermissionError()：构造身份或资源归属校验失败的异常，阻止后续操作。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
def actor_in(db, context):
    """查询数据库中的有效身份和会话归属；不使用模型传来的角色或操作人。"""
    user = db.execute(
        "SELECT * FROM users WHERE user_id=? AND active=1", (context.user_id,)
    ).fetchone()
    thread = db.execute(
        "SELECT 1 FROM threads WHERE thread_id=? AND user_id=?",
        (context.thread_id, context.user_id),
    ).fetchone()
    if not user or not thread:
        raise PermissionError("需要有效的账号和本人会话")
    return dict(user)


# 函数说明：visible
# 功能：纯权限判断：客户只读自己的工单，工作人员可读工作台工单。
# 内部调用：
#   - 无；本函数仅比较字段、返回固定值或返回对象本身。
def visible(user, ticket):
    """纯权限判断：客户只读自己的工单，工作人员可读工作台工单。"""
    return user["role"] != "customer" or ticket["owner_id"] == user["user_id"]


# 函数说明：read_ticket
# 功能：调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。
# 内部调用：
#   - storage.normalize_id()：用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - actor_in()：查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - visible()：纯权限判断：客户只读自己的工单，工作人员可读工作台工单。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
def read_ticket(context, ticket_id, history=False):
    """调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。"""
    normalized = storage.normalize_id(ticket_id)
    if not normalized:
        return storage.result(
            "get_ticket_status", False, "invalid_ticket_id", "请提供有效工单编号。"
        )
    try:
        with storage.connect(context.db_path) as db:
            user = actor_in(db, context)
            row = db.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (normalized,)
            ).fetchone()
            if not row or not visible(user, row):
                return storage.result(
                    "get_ticket_status", False, "not_found", "工单不存在或无权访问。"
                )
            events = (
                [
                    dict(event)
                    for event in db.execute(
                        "SELECT * FROM ticket_events WHERE ticket_id=? ORDER BY event_id",
                        (normalized,),
                    )
                ]
                if history
                else []
            )
            return storage.result("get_ticket_status", ticket=dict(row), history=events)
    except PermissionError:
        return storage.result(
            "get_ticket_status", False, "forbidden", "无权查询该工单。"
        )


# 函数说明：search_tickets
# 功能：按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。
# 内部调用：
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - datetime.strptime()：按 YYYY-MM-DD 解析日期，非法日期抛出 ValueError。
#   - ValueError()：构造无效参数或状态异常，交给调用方捕获和显示。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - actor_in()：查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。
#   - clauses.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - args.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - storage.normalize_id()：用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。
#   - product_model.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - product_model.strip(...).upper()：把字母转为大写，统一设备型号或错误码。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
def search_tickets(
    context,
    ticket_id="",
    product_model="",
    status="",
    created_from="",
    created_to="",
    mine=False,
):
    """按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。"""
    if status and status not in storage.STATUSES:
        return storage.result(
            "search_tickets", False, "invalid_fields", "工单状态无效。", tickets=[]
        )
    try:
        for value in (created_from, created_to):
            if value:
                datetime.strptime(value, "%Y-%m-%d")
        if created_from and created_to and created_from > created_to:
            raise ValueError()
    except ValueError:
        return storage.result(
            "search_tickets",
            False,
            "invalid_fields",
            "请检查起止日期（YYYY-MM-DD）。",
            tickets=[],
        )
    try:
        with storage.connect(context.db_path) as db:
            user = actor_in(db, context)
            clauses, args = ["1=1"], []
            if user["role"] == "customer" or mine:
                clauses.append("owner_id=?")
                args.append(context.user_id)
            for field, value in (
                ("ticket_id", storage.normalize_id(ticket_id) if ticket_id else ""),
                ("product_model", product_model.strip().upper()),
                ("status", status),
            ):
                if value:
                    clauses.append(f"{field}=?")
                    args.append(value)
            if ticket_id and not storage.normalize_id(ticket_id):
                return storage.result(
                    "search_tickets",
                    False,
                    "invalid_ticket_id",
                    "工单编号无效。",
                    tickets=[],
                )
            if created_from:
                clauses.append("substr(created_at,1,10)>=?")
                args.append(created_from)
            if created_to:
                clauses.append("substr(created_at,1,10)<=?")
                args.append(created_to)
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM tickets WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at DESC LIMIT 201",
                    args,
                )
            ]
            return storage.result(
                "search_tickets", tickets=rows[:200], truncated=len(rows) > 200
            )
    except PermissionError:
        return storage.result(
            "search_tickets", False, "forbidden", "请重新登录。", tickets=[]
        )


# 函数说明：priority_for
# 功能：以明确业务规则计算优先级；安全故障紧急，多设备影响高，其余普通。
# 内部调用：
#   - 无；本函数仅比较字段、返回固定值或返回对象本身。
def priority_for(issue_type, impact):
    """以明确业务规则计算优先级；安全故障紧急，多设备影响高，其余普通。"""
    return (
        "紧急"
        if issue_type == "safety"
        else "高"
        if impact in {"multiple", "all"}
        else "普通"
    )


# 函数说明：choose_assignee
# 功能：从真实维修人员中按型号/故障专长筛选，SELECT 统计未关闭数量后选择负载较低者。
# 内部调用：
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - candidates.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - min()：选择最小值；用于挑选负载较低的维修人员或限制并发上限。
def choose_assignee(db, product_model, issue_type):
    """从真实维修人员中按型号/故障专长筛选，SELECT 统计未关闭数量后选择负载较低者。"""
    candidates = []
    for row in db.execute("SELECT * FROM users WHERE role='technician' AND active=1"):
        models, kinds = json.loads(row["models"]), json.loads(row["specialties"])
        if models and product_model not in models:
            continue
        if kinds and issue_type not in kinds:
            continue
        load = db.execute(
            "SELECT count(*) FROM tickets WHERE assigned_to=? AND status NOT IN ('已解决','已关闭')",
            (row["user_id"],),
        ).fetchone()[0]
        candidates.append((load, row["user_id"]))
    return min(candidates)[1] if candidates else ""


# 函数说明：similar_tickets
# 功能：只比较同客户同型号未关闭工单；用故障类别及 SequenceMatcher 做可解释的相似提示。
# 内部调用：
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - SequenceMatcher()：建立两段故障文本的序列比较器，后续 ratio 给出相似程度。
#   - SequenceMatcher(...).ratio()：计算两段故障文本的相似比例（0 到 1），并与故障类别一起判断相似单。
#   - knowledge.classify_issue()：按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。
#   - payload.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - round()：按指定小数位四舍五入，使相似度、费用或耗时便于展示。
#   - matches.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
def similar_tickets(db, owner_id, payload):
    """只比较同客户同型号未关闭工单；用故障类别及 SequenceMatcher 做可解释的相似提示。"""
    matches = []
    for row in db.execute(
        "SELECT * FROM tickets WHERE owner_id=? AND product_model=? AND status!='已关闭'",
        (owner_id, payload["product_model"]),
    ):
        score = SequenceMatcher(
            None, row["issue_description"], payload["issue_description"]
        ).ratio()
        stored_kind = row["issue_type"]
        if stored_kind == "other":
            stored_kind = knowledge.classify_issue(row["issue_description"])
        if score >= 0.55 or (
            payload.get("issue_type") not in {None, "other"}
            and payload["issue_type"] == stored_kind
        ):
            matches.append(
                {
                    "ticket_id": row["ticket_id"],
                    "status": row["status"],
                    "issue_description": row["issue_description"],
                    "similarity": round(score, 3),
                }
            )
    return matches


# 函数说明：validate_update
# 功能：核对工单可见性、当前状态、角色、是否分派给本人及本次字段；允许时返回 None，不允许时返回统一错误结果。
# 内部调用：
#   - visible()：纯权限判断：客户只读自己的工单，工作人员可读工作台工单。
#   - fail()：通过 storage.result 构造当前操作的统一错误。
#   - payload.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - payload.get(...).strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
def validate_update(db, user, ticket, action, payload):
    """检查当前状态、归属、人员角色、字段和有限状态机；返回错误字典或 None。"""

    # 函数说明：validate_update.fail
    # 功能：通过 storage.result 构造当前操作的统一错误。
    # 内部调用：
    #   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
    def fail(code, message):
        """通过 storage.result 构造当前操作的统一错误。"""
        return storage.result(action, False, code, message)

    if not visible(user, ticket):
        return fail("forbidden", "无权操作该工单。")
    role, owner = user["role"], ticket["owner_id"] == user["user_id"]
    assigned = ticket["assigned_to"] == user["user_id"]
    worker = role == "admin" or (role == "technician" and assigned)
    if ticket["status"] == "已关闭":
        return fail("invalid_transition", "已关闭工单不可修改，请创建新工单。")
    if action == "update_ticket_status":
        target = payload.get("new_status")
        current = ticket["status"]
        if target not in TRANSITIONS[current]:
            return fail("invalid_transition", f"不允许从{current}变为{target}。")
        allowed = worker
        if target == "已关闭":
            allowed = owner or role in {"support", "admin"}
        elif current == "待用户确认" and target in {"已解决", "处理中"}:
            allowed = owner or worker
        if not allowed:
            return fail(
                "forbidden", "当前身份不能执行该状态变更；维修由分派的维修人员处理。"
            )
        if not payload.get("note", "").strip():
            return fail("missing_fields", "请填写处理说明。")
    elif action == "cancel_ticket":
        if ticket["status"] != "待处理":
            return fail("invalid_transition", "只有尚未处理的工单可以取消。")
        if not owner and role not in {"support", "admin"}:
            return fail("forbidden", "无权取消该工单。")
    elif action == "assign_ticket":
        if role not in {"support", "admin"}:
            return fail("forbidden", "只有客服或管理员可以分派工单。")
        assignee = db.execute(
            "SELECT * FROM users WHERE user_id=? AND role='technician' AND active=1",
            (payload.get("assignee_id", ""),),
        ).fetchone()
        if not assignee:
            return fail("invalid_assignee", "请选择有效维修人员。")
    elif action == "set_ticket_priority":
        if role not in {"support", "admin"}:
            return fail("forbidden", "只有客服或管理员可以调整优先级。")
        if payload.get("priority") not in {"普通", "高", "紧急"}:
            return fail("invalid_fields", "优先级应为普通、高或紧急。")
    elif action == "supplement_ticket":
        if not owner and role not in {"support", "admin"} and not worker:
            return fail("forbidden", "无权补充该工单。")
        if not any(
            payload.get(key, "").strip()
            for key in ("description", "contact", "device_info")
        ):
            return fail("missing_fields", "请至少补充一项信息。")
        if len(ticket["issue_description"] + payload.get("description", "")) > 4000:
            return fail("invalid_fields", "累计故障描述限 4000 字。")
    elif action == "handoff_ticket":
        if not payload.get("note", "").strip():
            return fail("missing_fields", "请说明转人工原因。")
    else:
        return fail("unknown_action", "未知操作。")
    return None


# 函数说明：propose
# 功能：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
# 内部调用：
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - actor_in()：查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - re.search()：查找第一处符合正则的内容；用于识别明确故障、失败反馈、禁止写操作或业务陈述。
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - value.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - payload.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - clean.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - clean.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - storage.validate_create()：纯参数校验；通过 result 返回缺字段/长度/请求编号错误，不写数据库。
#   - clean['product_model'].upper()：把字母转为大写，统一设备型号或错误码。
#   - knowledge.classify_issue()：按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。
#   - priority_for()：以明确业务规则计算优先级；安全故障紧急，多设备影响高，其余普通。
#   - choose_assignee()：从真实维修人员中按型号/故障专长筛选，SELECT 统计未关闭数量后选择负载较低者。
#   - similar_tickets()：只比较同客户同型号未关闭工单；用故障类别及 SequenceMatcher 做可解释的相似提示。
#   - storage.normalize_id()：用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。
#   - visible()：纯权限判断：客户只读自己的工单，工作人员可读工作台工单。
#   - validate_update()：核对工单可见性、当前状态、角色、是否分派给本人及本次字段；允许时返回 None，不允许时返回统一错误结果。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - original.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - clean.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - uuid4()：生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - storage.encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
#   - datetime.now()：读取当前日期时间；传入 UTC 以统一数据库时间与有效期。
#   - timedelta()：创建分钟或小时的时间差，加到当前时间后得到确认/登录的过期时间。
#   - (datetime.now(UTC) + timedelta(minutes=15)).isoformat()：把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。
#   - serialized.encode()：把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。
#   - hashlib.sha256()：计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。
#   - hashlib.sha256(...).hexdigest()：把哈希对象的结果转换为十六进制文本，用于存储与比较。
def propose(context, action, payload):
    """只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。"""
    if action not in WRITE_ACTIONS:
        return storage.result(action, False, "unknown_action", "未知操作。")
    if not context.request_id:
        return storage.result(action, False, "missing_request_id", "缺少应用请求编号。")
    try:
        with storage.connect(context.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            user = actor_in(db, context)
            request = db.execute(
                "SELECT * FROM requests WHERE request_id=? AND thread_id=? AND user_id=?",
                (context.request_id, context.thread_id, context.user_id),
            ).fetchone()
            if not request:
                return storage.result(
                    action, False, "missing_request_id", "请求与会话不匹配。"
                )
            if re.search(
                r"(不要|禁止|别|不许).{0,8}(建单|创建|提交|修改|关闭|取消|操作)",
                request["input"],
            ):
                return storage.result(
                    action, False, "operation_denied", "本次用户要求禁止写操作。"
                )
            clean = {
                key: value.strip() if isinstance(value, str) else value
                for key, value in payload.items()
            }
            if any(
                isinstance(value, str) and len(value) > 2000 for value in clean.values()
            ):
                return storage.result(action, False, "invalid_fields", "操作字段过长。")
            if action == "create_ticket":
                error = storage.validate_create(
                    clean.get("product_model"),
                    clean.get("issue_description"),
                    context.request_id,
                )
                if error:
                    return error
                clean["product_model"] = clean["product_model"].upper()
                clean["issue_type"] = knowledge.classify_issue(
                    clean["issue_description"]
                )
                if clean.get("impact", "single") not in {"single", "multiple", "all"}:
                    return storage.result(
                        action, False, "invalid_fields", "影响范围无效。"
                    )
                clean["impact"] = clean.get("impact", "single")
                clean["priority"] = priority_for(clean["issue_type"], clean["impact"])
                clean["assigned_to"] = choose_assignee(
                    db, clean["product_model"], clean["issue_type"]
                )
                clean["duplicates"] = similar_tickets(db, context.user_id, clean)
            else:
                clean["ticket_id"] = storage.normalize_id(clean.get("ticket_id"))
                row = db.execute(
                    "SELECT * FROM tickets WHERE ticket_id=?", (clean["ticket_id"],)
                ).fetchone()
                if not row or not visible(user, row):
                    return storage.result(
                        action, False, "not_found", "工单不存在或无权访问。"
                    )
                error = validate_update(db, user, row, action, clean)
                if error:
                    return error
                clean["expected_version"] = row["version"]
                clean["previous_status"] = row["status"]
            existing = db.execute(
                "SELECT * FROM pending_actions WHERE thread_id=? AND request_id=?",
                (context.thread_id, context.request_id),
            ).fetchone()
            if existing:
                # 忽略运行时重新统计的重复提示；业务参数必须与原提案完全一致。
                original = json.loads(existing["payload"])
                ignored = {
                    "duplicates",
                    "assigned_to",
                    "expected_version",
                    "previous_status",
                }
                if existing["action"] != action or {
                    k: v for k, v in original.items() if k not in ignored
                } != {k: v for k, v in clean.items() if k not in ignored}:
                    return storage.result(
                        action,
                        False,
                        "request_conflict",
                        "同一请求的操作参数发生变化，请重新提出请求。",
                    )
                if existing["state"] == "executed":
                    return {**json.loads(existing["result"]), "reused": True}
                if (
                    existing["state"] != "pending"
                    or existing["expires_at"] <= storage.now()
                ):
                    return storage.result(
                        action,
                        False,
                        "confirmation_expired",
                        "原确认已失效，请重新提出请求。",
                    )
                return storage.result(
                    action,
                    state="awaiting_confirmation",
                    operation_id=existing["operation_id"],
                    payload=original,
                    expires_at=existing["expires_at"],
                    reused=True,
                )
            operation_id = str(uuid4())
            serialized = storage.encode(clean)
            expiry = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
            db.execute(
                """INSERT INTO pending_actions
                (operation_id,thread_id,user_id,request_id,action,payload,payload_hash,expires_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    operation_id,
                    context.thread_id,
                    context.user_id,
                    context.request_id,
                    action,
                    serialized,
                    hashlib.sha256(serialized.encode()).hexdigest(),
                    expiry,
                    storage.now(),
                ),
            )
            return storage.result(
                action,
                state="awaiting_confirmation",
                operation_id=operation_id,
                payload=clean,
                expires_at=expiry,
            )
    except PermissionError:
        return storage.result(action, False, "forbidden", "登录身份或会话不匹配。")
    except sqlite3.OperationalError:
        return storage.result(
            action, False, "database_busy", "数据库暂不可用，请重试。"
        )


# 函数说明：pending_actions
# 功能：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - actor_in()：查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
def pending_actions(context):
    """检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。"""
    with storage.connect(context.db_path) as db:
        actor_in(db, context)
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM pending_actions WHERE thread_id=? AND user_id=? AND state='pending' AND expires_at>? ORDER BY created_at",
                (context.thread_id, context.user_id, storage.now()),
            )
        ]
    for row in rows:
        row["payload"] = json.loads(row["payload"])
    return rows


# 函数说明：confirm_action
# 功能：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - actor_in()：查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - visible()：纯权限判断：客户只读自己的工单，工作人员可读工作台工单。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - operation['payload'].encode()：把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。
#   - hashlib.sha256()：计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。
#   - hashlib.sha256(...).hexdigest()：把哈希对象的结果转换为十六进制文本，用于存储与比较。
#   - similar_tickets()：只比较同客户同型号未关闭工单；用故障类别及 SequenceMatcher 做可解释的相似提示。
#   - storage.insert_ticket()：可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。
#   - validate_update()：核对工单可见性、当前状态、角色、是否分派给本人及本次字段；允许时返回 None，不允许时返回统一错误结果。
#   - payload.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - changes.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - storage.record_change()：调用参数化 INSERT 在当前业务事务中保存前后快照；与工单修改一起提交。
#   - storage.encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
#   - sessions.TicketContext()：按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。
#   - sessions.TicketContext(...).model_dump()：把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。
#   - render_result()：完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。
#   - transcript.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
def confirm_action(context, operation_id, *, accept_duplicate=False, cancel=False):
    """页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。"""
    try:
        with storage.connect(context.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            user = actor_in(db, context)
            operation = db.execute(
                "SELECT * FROM pending_actions WHERE operation_id=? AND thread_id=? AND user_id=?",
                (operation_id, context.thread_id, context.user_id),
            ).fetchone()
            if not operation:
                return storage.result(
                    "confirm", False, "forbidden", "待确认操作不存在或不属于当前会话。"
                )
            action = operation["action"]
            if operation["state"] == "executed":
                cached = json.loads(operation["result"])
                ticket = db.execute(
                    "SELECT * FROM tickets WHERE ticket_id=?",
                    (cached["ticket"]["ticket_id"],),
                ).fetchone()
                if not ticket or not visible(user, ticket):
                    return storage.result(
                        action, False, "forbidden", "当前身份无权读取原操作结果。"
                    )
                return {
                    **cached,
                    "ticket": dict(ticket),
                    "current_status": ticket["status"],
                    "reused": True,
                }
            if (
                operation["state"] != "pending"
                or operation["expires_at"] <= storage.now()
            ):
                return storage.result(
                    action,
                    False,
                    "confirmation_expired",
                    "确认已过期或已撤销，请重新提出操作。",
                )
            if cancel:
                db.execute(
                    "UPDATE pending_actions SET state='cancelled' WHERE operation_id=?",
                    (operation_id,),
                )
                return storage.result(
                    action,
                    state="cancelled",
                    message="已撤销待确认操作，没有修改工单。",
                )
            if (
                hashlib.sha256(operation["payload"].encode()).hexdigest()
                != operation["payload_hash"]
            ):
                return storage.result(
                    action, False, "payload_changed", "确认参数不一致，拒绝执行。"
                )
            payload = json.loads(operation["payload"])
            if action == "create_ticket":
                duplicates = similar_tickets(db, context.user_id, payload)
                if {x["ticket_id"] for x in duplicates} - {
                    x["ticket_id"] for x in payload["duplicates"]
                }:
                    return storage.result(
                        action,
                        False,
                        "duplicate_changed",
                        "新增了相似工单，请重新发起请求核对。",
                    )
                if duplicates and not accept_duplicate:
                    return storage.result(
                        action,
                        False,
                        "duplicate_confirmation_required",
                        "请先查看相似工单，并勾选仍要新建。",
                        duplicates=duplicates,
                    )
                if (
                    payload["assigned_to"]
                    and not db.execute(
                        "SELECT 1 FROM users WHERE user_id=? AND active=1 AND role='technician'",
                        (payload["assigned_to"],),
                    ).fetchone()
                ):
                    return storage.result(
                        action,
                        False,
                        "invalid_assignee",
                        "原分派人员已失效，请重新发起请求。",
                    )
                outcome = storage.insert_ticket(
                    db, payload, operation["request_id"], context.user_id
                )
            else:
                row = db.execute(
                    "SELECT * FROM tickets WHERE ticket_id=?", (payload["ticket_id"],)
                ).fetchone()
                if not row or row["version"] != payload["expected_version"]:
                    return storage.result(
                        action,
                        False,
                        "stale_ticket",
                        "工单已被其他操作更新，请重新查看并发起操作。",
                    )
                error = validate_update(db, user, row, action, payload)
                if error:
                    return error
                before = dict(row)
                changes = {"version": row["version"] + 1, "updated_at": storage.now()}
                if action in {"update_ticket_status", "cancel_ticket"}:
                    changes["status"] = (
                        "已关闭" if action == "cancel_ticket" else payload["new_status"]
                    )
                elif action == "assign_ticket":
                    changes["assigned_to"] = payload["assignee_id"]
                elif action == "set_ticket_priority":
                    changes["priority"] = payload["priority"]
                elif action == "handoff_ticket":
                    changes["manual"] = 1
                elif action == "supplement_ticket":
                    for field in ("contact", "device_info"):
                        if payload.get(field):
                            changes[field] = payload[field]
                    if payload.get("description"):
                        changes["issue_description"] = (
                            row["issue_description"]
                            + "\n补充："
                            + payload["description"]
                        )
                db.execute(
                    "UPDATE tickets SET "
                    + ",".join(f"{key}=?" for key in changes)
                    + " WHERE ticket_id=?",
                    (*changes.values(), payload["ticket_id"]),
                )
                saved = dict(
                    db.execute(
                        "SELECT * FROM tickets WHERE ticket_id=?",
                        (payload["ticket_id"],),
                    ).fetchone()
                )
                storage.record_change(
                    db,
                    before,
                    saved,
                    context.user_id,
                    action,
                    payload.get("note") or payload.get("description", ""),
                )
                outcome = storage.result(
                    action,
                    ticket=saved,
                    previous_status=before["status"],
                    current_status=saved["status"],
                )
            db.execute(
                "UPDATE pending_actions SET state='executed',result=? WHERE operation_id=?",
                (storage.encode(outcome), operation_id),
            )
            thread = db.execute(
                "SELECT * FROM threads WHERE thread_id=?", (context.thread_id,)
            ).fetchone()
            memory = sessions.TicketContext(**json.loads(thread["memory"])).model_dump()
            memory["ticket_id"] = outcome["ticket"]["ticket_id"]
            memory["pending_action"] = None
            transcript = json.loads(thread["transcript"])
            transcript.append(
                {
                    "role": "assistant",
                    "content": render_result(outcome),
                    "time": storage.now(),
                    "operation_id": operation_id,
                }
            )
            db.execute(
                "UPDATE threads SET memory=?,transcript=?,updated_at=? WHERE thread_id=?",
                (
                    storage.encode(memory),
                    storage.encode(transcript),
                    storage.now(),
                    context.thread_id,
                ),
            )
            db.execute(
                """INSERT INTO execution_events(thread_id,request_id,user_id,kind,name,args,result,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    context.thread_id,
                    operation["request_id"],
                    context.user_id,
                    "confirmation",
                    action,
                    operation["payload"],
                    storage.encode(outcome),
                    storage.now(),
                ),
            )
        return outcome
    except PermissionError:
        return storage.result("confirm", False, "forbidden", "无权确认该操作。")
    except sqlite3.OperationalError:
        return storage.result(
            "confirm",
            False,
            "database_busy",
            "数据库暂不可用；可重试原确认，不会重复执行。",
        )


# 函数说明：render_result
# 功能：完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。
# 内部调用：
#   - outcome.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - ACTION_LABELS.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
def render_result(outcome):
    """完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。"""
    if not outcome.get("success"):
        return f"操作未完成：{outcome.get('message', '执行失败')}（{outcome.get('error_code', 'ERROR')}）"
    if outcome.get("state") == "awaiting_confirmation":
        return f"已整理{ACTION_LABELS.get(outcome['action'], '操作')}信息，尚未执行。请核对下方确认卡片，点击确认后生效。"
    if outcome.get("state") == "cancelled":
        return outcome["message"]
    if "ticket" in outcome:
        ticket = outcome["ticket"]
        prefix = (
            "数据库查询结果"
            if outcome["action"] == "get_ticket_status"
            else f"{ACTION_LABELS.get(outcome['action'], '操作')}已完成"
        )
        if outcome.get("reused"):
            prefix = "此前操作已完成，本次未重复执行；数据库记录"
        return f"{prefix}：{ticket['ticket_id']}，当前状态：{ticket['status']}。设备：{ticket['product_model']}；优先级：{ticket['priority']}；处理人：{ticket['assigned_to'] or '待分派'}。"
    if "tickets" in outcome:
        rows = outcome["tickets"]
        return "查询结果：\n" + (
            "\n".join(
                f"- {row['ticket_id']} · {row['product_model']} · {row['status']} · {row['priority']}"
                for row in rows
            )
            or "暂无符合条件的工单。"
        )
    return outcome.get("message") or "操作已完成。"
