"""本机账号认证。角色由数据库决定，不接受模型提供的 operator_id/role。"""

import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import UTC, datetime, timedelta

from react_agent import storage


# 函数说明：public_user
# 功能：只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。
# 内部调用：
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
def public_user(row):
    """只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。"""
    if not row:
        return None
    return {
        "user_id": row["user_id"],
        "role": row["role"],
        "active": bool(row["active"]),
        "models": json.loads(row["models"]),
        "specialties": json.loads(row["specialties"]),
    }


# 函数说明：get_user
# 功能：调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - public_user()：只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。
def get_user(user_id, db_path=None):
    """调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。"""
    with storage.connect(db_path) as db:
        return public_user(
            db.execute(
                "SELECT * FROM users WHERE user_id=? AND active=1", (user_id,)
            ).fetchone()
        )


# 函数说明：users
# 功能：供可信工作台列举人员；调用 connect/public_user 去除认证资料。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - public_user()：只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def users(db_path=None):
    """供可信工作台列举人员；调用 connect/public_user 去除认证资料。"""
    with storage.connect(db_path) as db:
        return [
            public_user(row)
            for row in db.execute("SELECT * FROM users WHERE active=1 ORDER BY user_id")
        ]


# 函数说明：password_digest
# 功能：调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。
# 内部调用：
#   - secrets.token_hex()：生成不可预测的十六进制随机盐，使相同密码得到不同散列。
#   - password.encode()：把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。
#   - salt.encode()：把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。
#   - hashlib.pbkdf2_hmac()：通过多轮加盐 HMAC 派生密码散列；这里使用 SHA256 和 600000 轮，不保存原始密码。
#   - hashlib.pbkdf2_hmac(...).hex()：把派生得到的字节串转换为十六进制文本，组成密码散列记录。
def password_digest(password, salt=None):
    """调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。"""
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 600_000
    ).hex()
    return f"{salt}${hashed}"


# 函数说明：create_user
# 功能：事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。
# 内部调用：
#   - re.fullmatch()：要求整段文本符合正则；用于账号/编号校验或排除工单编号被误当设备型号。
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - password_digest()：调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - storage.encode()：调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - get_user()：调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。
def create_user(
    user_id,
    password,
    role="customer",
    db_path=None,
    *,
    administrator="",
    bootstrap=False,
    models=None,
    specialties=None,
):
    """事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。"""
    if (
        not re.fullmatch(r"[A-Za-z0-9_\-]{3,40}", user_id or "")
        or not isinstance(password, str)
        or not 8 <= len(password) <= 128
    ):
        return storage.result(
            "register",
            False,
            "invalid_fields",
            "账号需 3–40 位字母数字或下划线，密码需 8–128 位。",
        )
    if role not in storage.ROLES:
        return storage.result("register", False, "invalid_role", "未知角色。")
    digest = password_digest(password)
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT count(*) FROM users").fetchone()[0]
        admin = db.execute(
            "SELECT role FROM users WHERE user_id=? AND active=1", (administrator,)
        ).fetchone()
        if bootstrap:
            if count or role != "admin":
                return storage.result(
                    "register", False, "forbidden", "首次管理员设置已经完成。"
                )
        elif role != "customer" and (not admin or admin[0] != "admin"):
            return storage.result(
                "register", False, "forbidden", "只有管理员能创建工作人员。"
            )
        if db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            return storage.result("register", False, "already_exists", "账号已经存在。")
        db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,1,?)",
            (
                user_id,
                digest,
                role,
                storage.encode(models or []),
                storage.encode(specialties or []),
                storage.now(),
            ),
        )
    return storage.result("register", user=get_user(user_id, db_path))


# 函数说明：login
# 功能：调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。
# 内部调用：
#   - consume_login_budget()：在 SQLite 中按账号/来源计数，超出一分钟窗口限额时拒绝本次尝试。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - password_digest()：调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。
#   - digest.split()：按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。
#   - hmac.compare_digest()：比较两个散列结果，减少普通字符串比较可能带来的时序差异。
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - secrets.token_urlsafe()：生成可放进 URL 的高随机性登录令牌，数据库只保存其散列。
#   - datetime.now()：读取当前日期时间；传入 UTC 以统一数据库时间与有效期。
#   - timedelta()：创建分钟或小时的时间差，加到当前时间后得到确认/登录的过期时间。
#   - (datetime.now(UTC) + timedelta(hours=12)).isoformat()：把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。
#   - token.encode()：把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。
#   - hashlib.sha256()：计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。
#   - hashlib.sha256(...).hexdigest()：把哈希对象的结果转换为十六进制文本，用于存储与比较。
#   - public_user()：只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。
def consume_login_budget(user_id, db_path=None, client_key=None):
    """功能：限制账号每分钟 10 次、来源每分钟 30 次登录尝试；调用 SHA256 隐藏键、time.time 计时、connect/execute 原子计数并清理旧窗口。"""
    current = time.time()
    buckets = [("account:" + user_id, 10)]
    if client_key:
        buckets.append(("source:" + client_key, 30))
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM auth_limits WHERE started_at<?", (current - 3600,))
        for key, limit in buckets:
            hashed = hashlib.sha256(key.encode()).hexdigest()
            row = db.execute(
                "SELECT * FROM auth_limits WHERE bucket=?", (hashed,)
            ).fetchone()
            if row and current - row["started_at"] < 60 and row["attempts"] >= limit:
                return False
        for key, _ in buckets:
            hashed = hashlib.sha256(key.encode()).hexdigest()
            db.execute(
                """INSERT INTO auth_limits VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET
                attempts=CASE WHEN started_at>? THEN attempts+1 ELSE 1 END,
                started_at=CASE WHEN started_at>? THEN started_at ELSE excluded.started_at END""",
                (hashed, current, current - 60, current - 60),
            )
    return True


def login(user_id, password, db_path=None, *, client_key=None):
    """先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。"""
    if (
        not isinstance(user_id, str)
        or not isinstance(password, str)
        or len(user_id) > 40
        or len(password) > 128
    ):
        return storage.result("login", False, "invalid_credentials", "账号或密码错误。")
    if not consume_login_budget(user_id, db_path, client_key):
        return storage.result(
            "login", False, "rate_limited", "登录尝试过于频繁，请一分钟后再试。"
        )
    with storage.connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM users WHERE user_id=? AND active=1", (user_id,)
        ).fetchone()
        digest = row["password_hash"] if row else password_digest("dummy-password")
        valid = hmac.compare_digest(
            password_digest(password, digest.split("$")[0]), digest
        )
        if not row or not valid:
            return storage.result(
                "login", False, "invalid_credentials", "账号或密码错误。"
            )
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(UTC) + timedelta(hours=12)).isoformat()
        db.execute(
            "INSERT INTO login_sessions VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, expires),
        )
    return storage.result("login", token=token, user=public_user(row))


# 函数说明：authenticate
# 功能：调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。
# 内部调用：
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - token.encode()：把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。
#   - hashlib.sha256()：计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。
#   - hashlib.sha256(...).hexdigest()：把哈希对象的结果转换为十六进制文本，用于存储与比较。
#   - storage.now()：返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - db.execute(...).fetchone()：从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。
#   - public_user()：只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。
def authenticate(token, db_path=None):
    """调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。"""
    if not token or not isinstance(token, str):
        return None
    with storage.connect(db_path) as db:
        row = db.execute(
            """SELECT u.* FROM users u JOIN login_sessions s ON s.user_id=u.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
            (hashlib.sha256(token.encode()).hexdigest(), storage.now()),
        ).fetchone()
    return public_user(row)


# 函数说明：logout
# 功能：调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。
# 内部调用：
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - token.encode()：把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。
#   - hashlib.sha256()：计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。
#   - hashlib.sha256(...).hexdigest()：把哈希对象的结果转换为十六进制文本，用于存储与比较。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
def logout(token, db_path=None):
    """调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。"""
    with storage.connect(db_path) as db:
        db.execute(
            "DELETE FROM login_sessions WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
