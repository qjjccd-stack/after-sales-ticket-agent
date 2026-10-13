"""SQLite 数据、无损迁移和可信内部建单。对外写操作统一经过 actions.confirm_action。"""

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("待处理", "处理中", "待用户确认", "已解决", "已关闭")
ROLES = ("customer", "technician", "support", "admin")


# 函数说明：now
# 功能：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
# 内部调用：
#   - datetime.now()：读取当前日期时间；传入 UTC 以统一数据库时间与有效期。
#   - datetime.now(...).isoformat()：把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。
def now() -> str:
    """返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。"""
    return datetime.now(UTC).isoformat()


# 函数说明：encode
# 功能：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
# 内部调用：
#   - json.dumps()：把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。
def encode(value) -> str:
    """调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# 函数说明：result
# 功能：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
# 内部调用：
#   - error.upper()：把字母转为大写，统一设备型号或错误码。
def result(
    action: str, success: bool = True, error: str = "", message: str = "", **data
):
    """统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。"""
    return {
        "ok": success,
        "success": success,
        "action": action,
        "error": error,
        "error_code": error.upper(),
        "retryable": error in {"database_busy", "timeout", "network_error"},
        "message": message,
        **data,
    }


# 函数说明：database_path
# 功能：调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。
# 内部调用：
#   - os.getenv()：读取环境变量，可指定默认值；读取的是当前进程配置。
#   - Path()：构造文件路径对象，便于拼接路径、判断绝对路径和读取本地文件。
#   - Path(...).expanduser()：把路径中的 ~ 展开为当前用户目录。
#   - target.is_absolute()：判断数据库路径是否已是绝对路径，否则相对项目根目录解析。
def database_path(path: str | None = None) -> Path:
    """调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。"""
    target = Path(
        path or os.getenv("TICKET_DB_PATH", "data/tickets.sqlite3")
    ).expanduser()
    return target if target.is_absolute() else ROOT / target


# 函数说明：migrate
# 功能：在写事务中建表、按 PRAGMA table_info 增列；不删除或重新编号原工单。
# 内部调用：
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - additions.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - db.commit()：提交本次迁移事务，使新增表、列及版本号一起生效。
def migrate(db):
    """在写事务中建表、按 PRAGMA table_info 增列；不删除或重新编号原工单。"""
    db.execute("BEGIN IMMEDIATE")
    db.execute("""CREATE TABLE IF NOT EXISTS tickets (
        ticket_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
        product_model TEXT NOT NULL, issue_description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '待处理', created_at TEXT NOT NULL)""")
    additions = {
        "owner_id": "TEXT NOT NULL DEFAULT 'legacy'",
        "issue_type": "TEXT NOT NULL DEFAULT 'other'",
        "impact": "TEXT NOT NULL DEFAULT 'single'",
        "priority": "TEXT NOT NULL DEFAULT '普通'",
        "assigned_to": "TEXT NOT NULL DEFAULT ''",
        "contact": "TEXT NOT NULL DEFAULT ''",
        "device_info": "TEXT NOT NULL DEFAULT ''",
        "manual": "INTEGER NOT NULL DEFAULT 0",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    columns = {row[1] for row in db.execute("PRAGMA table_info(tickets)")}
    for name, declaration in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE tickets ADD COLUMN {name} {declaration}")
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL,
            models TEXT NOT NULL DEFAULT '[]', specialties TEXT NOT NULL DEFAULT '[]',
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS login_sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
            memory TEXT NOT NULL DEFAULT '{}', transcript TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, user_id TEXT NOT NULL,
            input TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            output TEXT NOT NULL DEFAULT '{}', lease_until REAL NOT NULL DEFAULT 0,
            lease_token TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS pending_actions (
            operation_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, user_id TEXT NOT NULL,
            request_id TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
            payload_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            expires_at TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            UNIQUE(thread_id, request_id))""",
        """CREATE TABLE IF NOT EXISTS ticket_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL,
            operator_id TEXT NOT NULL, action TEXT NOT NULL, note TEXT NOT NULL,
            before_data TEXT NOT NULL, after_data TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS execution_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
            request_id TEXT NOT NULL, user_id TEXT NOT NULL, kind TEXT NOT NULL,
            name TEXT NOT NULL, args TEXT NOT NULL, result TEXT NOT NULL,
            elapsed_ms REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS tickets_owner_status ON tickets(owner_id,status)",
        "CREATE INDEX IF NOT EXISTS tickets_updated ON tickets(updated_at)",
        "CREATE INDEX IF NOT EXISTS threads_owner ON threads(user_id,updated_at)",
        "CREATE INDEX IF NOT EXISTS events_thread ON execution_events(thread_id,event_id)",
        """CREATE TABLE IF NOT EXISTS auth_limits (
            bucket TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS model_admissions (
            admission_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, user_id TEXT NOT NULL,
            day TEXT NOT NULL, started_at REAL NOT NULL, expires_at REAL NOT NULL,
            reserved_tokens INTEGER NOT NULL, charged_tokens INTEGER NOT NULL,
            reserved_cost_micro INTEGER NOT NULL, charged_cost_micro INTEGER NOT NULL,
            state TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS model_admissions_day ON model_admissions(day,user_id)",
        "CREATE INDEX IF NOT EXISTS model_admissions_active ON model_admissions(state,expires_at)",
        "CREATE INDEX IF NOT EXISTS model_admissions_user_time ON model_admissions(user_id,started_at)",
    ]
    for statement in statements:
        db.execute(statement)
    # v3：HTTP 提交幂等键随原请求原子保存，避免响应丢失后重新生成业务请求。
    request_columns = {row[1] for row in db.execute("PRAGMA table_info(requests)")}
    if "client_key" not in request_columns:
        db.execute("ALTER TABLE requests ADD COLUMN client_key TEXT")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS requests_client_key ON requests(user_id,client_key) WHERE client_key IS NOT NULL"
    )
    # v4：模型执行席位与日预算持久化，应用重启后仍按已预留/结算用量检查。
    db.execute("PRAGMA user_version=4")
    db.commit()


# 函数说明：connect
# 功能：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
# 内部调用：
#   - database_path()：调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。
#   - target.parent.mkdir()：创建输出或数据库父目录；parents/exist_ok 允许补齐父级并复用现有目录。
#   - sqlite3.connect()：打开指定 SQLite 文件连接；迁移测试也用它建立原始旧表，绕开应用迁移逻辑。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - migrate()：在写事务中建表、按 PRAGMA table_info 增列；不删除或重新编号原工单。
#   - db.close()：关闭 SQLite 连接，释放文件和事务资源；finally 保证异常时也执行。
# 装饰器：
#   - @contextmanager：把含 yield 的 connect 函数转换为 with 上下文管理器，进入时打开连接，退出时继续执行提交/回滚及关闭流程。
@contextmanager
def connect(path: str | None = None):
    """调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。"""
    target = database_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=3)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA busy_timeout=3000")
        if db.execute("PRAGMA user_version").fetchone()[0] < 4:
            migrate(db)
        with db:
            yield db
    finally:
        db.close()


# 函数说明：normalize_id
# 功能：用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。
# 内部调用：
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - ticket_id.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - re.fullmatch()：要求整段文本符合正则；用于账号/编号校验或排除工单编号被误当设备型号。
#   - int()：转换为整数；在工单编号中去掉数字前导零，再由格式化补成规范编号。
def normalize_id(ticket_id: str) -> str | None:
    """用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。"""
    if isinstance(ticket_id, str) and re.fullmatch(
        r"[Tt][0-9]{1,12}", ticket_id.strip()
    ):
        return f"T{int(ticket_id.strip()[1:]):04d}"
    return None


# 函数说明：validate_create
# 功能：纯参数校验；通过 result 返回缺字段/长度/请求编号错误，不写数据库。
# 内部调用：
#   - values.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - v.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - product_model.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - issue_description.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - request_id.strip()：去除文本两端空白，规范输入或判断是否只含空白。
def validate_create(product_model, issue_description, request_id):
    """纯参数校验；通过 result 返回缺字段/长度/请求编号错误，不写数据库。"""
    values = {"product_model": product_model, "issue_description": issue_description}
    missing = [k for k, v in values.items() if not isinstance(v, str) or not v.strip()]
    if missing:
        return result(
            "create_ticket",
            False,
            "missing_fields",
            "请补充产品型号和问题描述。",
            fields=missing,
        )
    if len(product_model.strip()) > 80 or len(issue_description.strip()) > 2000:
        return result(
            "create_ticket", False, "invalid_fields", "型号限 80 字，描述限 2000 字。"
        )
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or len(request_id) > 128
    ):
        return result(
            "create_ticket", False, "missing_request_id", "缺少有效的应用请求编号。"
        )
    return None


# 函数说明：record_change
# 功能：调用参数化 INSERT 在当前业务事务中保存前后快照；与工单修改一起提交。
# 内部调用：
#   - encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
#   - now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def record_change(db, before, after, operator_id, action, note=""):
    """调用参数化 INSERT 在当前业务事务中保存前后快照；与工单修改一起提交。"""
    db.execute(
        """INSERT INTO ticket_events
        (ticket_id,operator_id,action,note,before_data,after_data,created_at)
        VALUES (?,?,?,?,?,?,?)""",
        (
            after["ticket_id"],
            operator_id,
            action,
            note,
            encode(before),
            encode(after),
            now(),
        ),
    )


# 函数说明：insert_ticket
# 功能：可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。
# 内部调用：
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - payload.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - ticket.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - tuple()：把值序列固定为元组，以便作为 SQL 的位置参数传入。
#   - record_change()：调用参数化 INSERT 在当前业务事务中保存前后快照；与工单修改一起提交。
def insert_ticket(db, payload, request_id, owner_id="legacy"):
    """可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。"""
    existing = db.execute(
        "SELECT * FROM tickets WHERE request_id=?", (request_id,)
    ).fetchone()
    if existing:
        if (
            existing["product_model"],
            existing["issue_description"],
            existing["owner_id"],
        ) != (payload["product_model"], payload["issue_description"], owner_id):
            return result(
                "create_ticket",
                False,
                "request_conflict",
                "重试参数不同，未新增工单。",
                ticket=dict(existing),
            )
        return result("create_ticket", ticket=dict(existing), reused=True)
    number = db.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(ticket_id,2) AS INTEGER)),0)+1 FROM tickets"
    ).fetchone()[0]
    stamp = now()
    ticket = {
        "ticket_id": f"T{number:04d}",
        "request_id": request_id,
        "product_model": payload["product_model"],
        "issue_description": payload["issue_description"],
        "status": "待处理",
        "created_at": stamp,
        "updated_at": stamp,
        "owner_id": owner_id,
        "issue_type": payload.get("issue_type", "other"),
        "impact": payload.get("impact", "single"),
        "priority": payload.get("priority", "普通"),
        "assigned_to": payload.get("assigned_to", ""),
        "contact": payload.get("contact", ""),
        "device_info": payload.get("device_info", ""),
        "manual": 0,
        "version": 1,
    }
    keys = list(ticket)
    db.execute(
        f"INSERT INTO tickets ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
        tuple(ticket.values()),
    )
    saved = dict(
        db.execute(
            "SELECT * FROM tickets WHERE ticket_id=?", (ticket["ticket_id"],)
        ).fetchone()
    )
    record_change(db, {}, saved, owner_id, "create_ticket", "确认后建单")
    return result("create_ticket", ticket=saved, reused=False)


# 函数说明：create_ticket
# 功能：兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。
# 内部调用：
#   - validate_create()：纯参数校验；通过 result 返回缺字段/长度/请求编号错误，不写数据库。
#   - connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - product_model.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - issue_description.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - request_id.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - insert_ticket()：可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。
def create_ticket(
    product_model: str,
    issue_description: str,
    request_id: str,
    db_path: str | None = None,
) -> dict:
    """兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。"""
    error = validate_create(product_model, issue_description, request_id)
    if error:
        return error
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        return insert_ticket(
            db,
            {
                "product_model": product_model.strip(),
                "issue_description": issue_description.strip(),
            },
            request_id.strip(),
        )


# 函数说明：get_ticket_status
# 功能：可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。
# 内部调用：
#   - normalize_id()：用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。
#   - result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
def get_ticket_status(ticket_id: str, db_path: str | None = None) -> dict:
    """可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。"""
    normalized = normalize_id(ticket_id)
    if not normalized:
        return result(
            "get_ticket_status",
            False,
            "invalid_ticket_id",
            "请提供 T0001 格式的工单编号。",
        )
    with connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM tickets WHERE ticket_id=?", (normalized,)
        ).fetchone()
    if row is None:
        return result(
            "get_ticket_status",
            False,
            "not_found",
            "工单不存在。",
            ticket_id=normalized,
        )
    return result("get_ticket_status", ticket=dict(row))


# 函数说明：list_tickets
# 功能：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
# 内部调用：
#   - connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - dict()：把数据库行或键值对转换成可按字段访问的普通字典。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def list_tickets(db_path: str | None = None) -> list[dict]:
    """可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。"""
    with connect(db_path) as db:
        return [
            dict(row)
            for row in db.execute("SELECT * FROM tickets ORDER BY created_at DESC")
        ]


# 函数说明：log_execution
# 功能：调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。
# 内部调用：
#   - connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
#   - now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def log_execution(context, kind, name, args, outcome, elapsed_ms=0):
    """调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。"""
    with connect(context.db_path) as db:
        db.execute(
            """INSERT INTO execution_events
            (thread_id,request_id,user_id,kind,name,args,result,elapsed_ms,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                context.thread_id,
                context.request_id,
                context.user_id,
                kind,
                name,
                encode(args),
                encode(outcome),
                elapsed_ms,
                now(),
            ),
        )
