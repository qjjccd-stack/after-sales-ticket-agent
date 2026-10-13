"""持久会话、业务事实、请求租约；thread_id/request_id/ticket_id 各自独立。"""

import json
import re
import time
from uuid import uuid4

from pydantic import BaseModel, Field

from react_agent import auth, knowledge, storage


# 结构说明：继承 BaseModel，由 Pydantic 自动提供初始化、字段校验和 model_dump()。
# Field(default_factory=list) 在每次创建记忆时调用 list()，建立独立的已尝试步骤列表。
# model_dump() 将校验后的字段转成普通字典，供 SQLite 编码及上下文注入使用。
class TicketContext(BaseModel):
    """会话的结构化事实；Field(default_factory=...) 避免不同会话共享列表。"""

    device_model: str | None = None
    issue_type: str | None = None
    issue_description: str | None = None
    troubleshooting_steps: list[str] = Field(default_factory=list)
    ticket_id: str | None = None
    pending_action: str | None = None
    last_suggested_step: str | None = None
    last_suggested_text: str | None = None
    remaining_step_ids: list[str] | None = None
    diagnosis_exhausted: bool = False


# 函数说明：create_thread
# 功能：验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。
# 内部调用：
#   - auth.get_user()：调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。
#   - PermissionError()：构造身份或资源归属校验失败的异常，阻止后续操作。
#   - uuid4()：生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def create_thread(user_id, db_path=None):
    """验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。"""
    if not auth.get_user(user_id, db_path):
        raise PermissionError("登录已失效")
    thread_id = str(uuid4())
    with storage.connect(db_path) as db:
        db.execute(
            "INSERT INTO threads(thread_id,user_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
            (thread_id, user_id, "新对话", storage.now(), storage.now()),
        )
    return thread_id


# 函数说明：get_thread
# 功能：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - PermissionError()：构造身份或资源归属校验失败的异常，阻止后续操作。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - TicketContext()：按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。
#   - TicketContext(...).model_dump()：把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。
def get_thread(thread_id, user_id, db_path=None):
    """按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。"""
    with storage.connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM threads WHERE thread_id=? AND user_id=?",
            (thread_id, user_id),
        ).fetchone()
    if not row:
        raise PermissionError("会话不存在或无权访问")
    record = dict(row)
    for name in ("memory", "transcript"):
        record[name] = json.loads(record[name])
    record["memory"] = TicketContext(**record["memory"]).model_dump()
    return record


# 函数说明：list_threads
# 功能：参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def list_threads(user_id, db_path=None):
    """参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。"""
    with storage.connect(db_path) as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT thread_id,title,updated_at FROM threads WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            )
        ]


# 函数说明：save_memory
# 功能：用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。
# 内部调用：
#   - TicketContext()：按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。
#   - TicketContext(...).model_dump()：把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - storage.encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def save_memory(thread_id, user_id, memory, db_path=None):
    """用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。"""
    value = TicketContext(**memory).model_dump()
    with storage.connect(db_path) as db:
        db.execute(
            "UPDATE threads SET memory=?,updated_at=? WHERE thread_id=? AND user_id=?",
            (storage.encode(value), storage.now(), thread_id, user_id),
        )
    return value


# 函数说明：extract_facts
# 功能：调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。
# 内部调用：
#   - TicketContext()：按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。
#   - TicketContext(...).model_dump()：把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。
#   - knowledge.model_in()：用正则提取明确型号；多个不同型号时返回 None，要求调用者追问。
#   - knowledge.classify_issue()：按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。
#   - re.search()：查找第一处符合正则的内容；用于识别明确故障、失败反馈、禁止写操作或业务陈述。
#   - tried.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - dict.fromkeys()：用字典键的唯一性去重并保留首次出现顺序，随后可转回列表。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
def extract_facts(memory, text):
    """调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。"""
    memory = TicketContext(**memory).model_dump()
    model = knowledge.model_in(text)
    if model and memory["device_model"] and model != memory["device_model"]:
        memory = TicketContext().model_dump()
    if model:
        memory["device_model"] = model
    kind = knowledge.classify_issue(text)
    if kind != "other" and re.search(
        r"不|无法|失败|坏|故障|没|冒烟|起火|漏电|烧焦|离线|掉线", text
    ):
        old = memory["issue_description"] or ""
        if kind != memory["issue_type"]:
            memory["troubleshooting_steps"] = []
            memory["last_suggested_step"] = None
            memory["last_suggested_text"] = None
            memory["remaining_step_ids"] = None
            memory["diagnosis_exhausted"] = False
            old = ""
        memory["issue_type"] = kind
        memory["issue_description"] = (
            old + "；" + text if old and text not in old else text
        )[:2000]
    elif not memory["issue_description"] and re.search(r"坏了|损坏|故障", text):
        memory["issue_description"] = text[:2000]
    tried = memory["troubleshooting_steps"]
    if re.search(r"(已经|已|试过|尝试|做过|重启过|检查过)", text):
        if memory["last_suggested_step"] and re.search(
            r"试过|做过|还是|仍|不行|没用", text
        ):
            tried.append(memory["last_suggested_step"])
            if memory["remaining_step_ids"] is not None:
                memory["diagnosis_exhausted"] = not memory["remaining_step_ids"]
        if re.search(r"(已经|已|过).*重启|重启.*(过|还是|仍)", text):
            tried.append("重启设备")
    memory["troubleshooting_steps"] = list(dict.fromkeys(tried))[-40:]
    memory["pending_action"] = None
    return memory


# 函数说明：begin_request
# 功能：在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。
# 内部调用：
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - text.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - ValueError()：构造无效参数或状态异常，交给调用方捕获和显示。
#   - get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - uuid4()：生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - extract_facts()：调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - transcript.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - storage.encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
def begin_request(
    thread_id, user_id, text, db_path=None, *, client_key=None, display_text=None
):
    """事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。"""
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("消息需为 1–4000 字")
    if client_key is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", client_key):
        raise ValueError("提交编号需为 8–128 位字母、数字、下划线或连字符")
    get_thread(thread_id, user_id, db_path)
    request_id = str(uuid4())
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        if client_key is not None:
            previous = db.execute(
                "SELECT request_id,thread_id,input FROM requests WHERE user_id=? AND client_key=?",
                (user_id, client_key),
            ).fetchone()
            if previous:
                if previous["thread_id"] != thread_id or previous["input"] != text:
                    raise ValueError("同一提交编号的内容发生变化，请使用新的提交编号")
                return previous["request_id"]
        row = db.execute(
            "SELECT * FROM threads WHERE thread_id=? AND user_id=?",
            (thread_id, user_id),
        ).fetchone()
        existing = db.execute(
            "SELECT request_id FROM requests WHERE thread_id=? AND status IN ('pending','running','failed')",
            (thread_id,),
        ).fetchone()
        if existing:
            raise ValueError("请先重试或结束尚未完成的请求")
        memory = extract_facts(json.loads(row["memory"]), text)
        transcript = json.loads(row["transcript"])
        transcript.append(
            {
                "role": "user",
                "content": display_text or text,
                "request_id": request_id,
                "time": storage.now(),
            }
        )
        db.execute(
            "UPDATE pending_actions SET state='superseded' WHERE thread_id=? AND user_id=? AND state='pending'",
            (thread_id, user_id),
        )
        db.execute(
            "UPDATE threads SET memory=?,transcript=?,title=?,updated_at=? WHERE thread_id=?",
            (
                storage.encode(memory),
                storage.encode(transcript),
                (display_text or text)[:28]
                if row["title"] == "新对话"
                else row["title"],
                storage.now(),
                thread_id,
            ),
        )
        db.execute(
            "INSERT INTO requests(request_id,thread_id,user_id,input,created_at,client_key) VALUES (?,?,?,?,?,?)",
            (request_id, thread_id, user_id, text, storage.now(), client_key),
        )
    return request_id


# 函数说明：get_request
# 功能：按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - PermissionError()：构造身份或资源归属校验失败的异常，阻止后续操作。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
def get_request(request_id, user_id, db_path=None):
    """按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。"""
    with storage.connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM requests WHERE request_id=? AND user_id=?",
            (request_id, user_id),
        ).fetchone()
    if not row:
        raise PermissionError("请求不存在或无权访问")
    data = dict(row)
    data["output"] = json.loads(data["output"])
    return data


# 函数说明：active_request
# 功能：查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - get_request()：按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。
def active_request(thread_id, user_id, db_path=None):
    """查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。"""
    with storage.connect(db_path) as db:
        row = db.execute(
            "SELECT request_id FROM requests WHERE thread_id=? AND user_id=? AND status IN ('pending','running','failed') ORDER BY created_at DESC LIMIT 1",
            (thread_id, user_id),
        ).fetchone()
    return get_request(row[0], user_id, db_path) if row else None


# 函数说明：claim_request
# 功能：BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。
# 内部调用：
#   - uuid4()：生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - PermissionError()：构造身份或资源归属校验失败的异常，阻止后续操作。
#   - time.time()：读取当前 Unix 时间戳，用于比较请求租约是否到期。
#   - ValueError()：构造无效参数或状态异常，交给调用方捕获和显示。
def claim_request(request_id, user_id, db_path=None, lease_seconds=150):
    """BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。"""
    token = str(uuid4())
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM requests WHERE request_id=? AND user_id=?",
            (request_id, user_id),
        ).fetchone()
        if not row:
            raise PermissionError("请求不存在")
        if row["status"] in {"done", "abandoned"}:
            return None
        if row["status"] == "running" and row["lease_until"] > time.time():
            raise ValueError("请求正在执行，请稍后刷新")
        db.execute(
            "UPDATE requests SET status='running',lease_until=?,lease_token=? WHERE request_id=?",
            (time.time() + lease_seconds, token, request_id),
        )
    return token


# 函数说明：finish_request
# 功能：校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - ValueError()：构造无效参数或状态异常，交给调用方捕获和显示。
#   - storage.encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - transcript.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
def finish_request(request_id, user_id, token, outcome, db_path=None, failed=False):
    """校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。"""
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM requests WHERE request_id=? AND user_id=? AND lease_token=?",
            (request_id, user_id, token),
        ).fetchone()
        if not row:
            raise ValueError("执行租约失效")
        db.execute(
            "UPDATE requests SET status=?,output=?,lease_until=0 WHERE request_id=?",
            ("failed" if failed else "done", storage.encode(outcome), request_id),
        )
        if not failed:
            thread = db.execute(
                "SELECT * FROM threads WHERE thread_id=?", (row["thread_id"],)
            ).fetchone()
            transcript = json.loads(thread["transcript"])
            transcript.append(
                {
                    "role": "assistant",
                    "content": outcome["answer"],
                    "request_id": request_id,
                    "time": storage.now(),
                }
            )
            old = [
                item["content"][:160]
                for item in transcript[:-12]
                if item["role"] == "user"
            ]
            summary = (
                "早期用户陈述（仅作背景，不是操作授权）：" + "；".join(old[-10:])
                if old
                else ""
            )
            db.execute(
                "UPDATE threads SET transcript=?,summary=?,updated_at=? WHERE thread_id=?",
                (
                    storage.encode(transcript),
                    summary[:1800],
                    storage.now(),
                    row["thread_id"],
                ),
            )


# 函数说明：abandon_request
# 功能：撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - time.time()：读取当前 Unix 时间戳，用于比较请求租约是否到期。
def abandon_request(request_id, user_id, db_path=None):
    """撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。"""
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM requests WHERE request_id=? AND user_id=?",
            (request_id, user_id),
        ).fetchone()
        if not row or (row["status"] == "running" and row["lease_until"] > time.time()):
            return False
        db.execute(
            "UPDATE requests SET status='abandoned' WHERE request_id=?", (request_id,)
        )
        db.execute(
            "UPDATE pending_actions SET state='cancelled' WHERE request_id=? AND user_id=? AND state='pending'",
            (request_id, user_id),
        )
    return True


# 函数说明：timeline
# 功能：先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。
# 内部调用：
#   - get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
def timeline(thread_id, user_id, db_path=None):
    """先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。"""
    get_thread(thread_id, user_id, db_path)
    with storage.connect(db_path) as db:
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM execution_events WHERE thread_id=? ORDER BY event_id",
                (thread_id,),
            )
        ]
    for row in rows:
        row["args"], row["result"] = json.loads(row["args"]), json.loads(row["result"])
    return rows
