"""HTTP 演示版的持久用量门禁：先预留预算，再执行模型；异常结果未知时不退款。"""

import math
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from uuid import uuid4

from react_agent import storage


class LimitReached(Exception):
    """携带可公开的限额原因及重试等待时间，不包含模型密钥或业务正文。"""

    def __init__(self, code, message, retry_after=60):
        """功能：保存限额结果；Exception 初始化说明，ceil/max 将等待秒数规范为正整数。"""
        super().__init__(message)
        self.code = code
        self.retry_after = max(1, math.ceil(retry_after))


def positive_integer(name, default):
    """功能：读取正整数配置；getenv/int 转换参数，错误时拒绝启动，避免意外关闭限额。"""
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} 必须为正整数")
    return value


def decimal_setting(name):
    """功能：读取可选金额/单价；Decimal 与 is_finite 拒绝负数、NaN 和无穷，不使用浮点数记账。"""
    text = os.getenv(name, "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"{name} 必须是非负数") from error
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} 必须是非负有限数")
    return value


def micro_amount(value):
    """功能：把 Decimal 向上取整为微单位；to_integral_value 避免低估不足一微单位的费用。"""
    return int(value.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class DemoLimits:
    """应用拥有的限额配置；金额统一使用配置单价的币种，数据库保存百万分之一币种单位。"""

    concurrent: int = 2
    per_minute: int = 6
    user_daily_tokens: int = 100_000
    daily_tokens: int = 500_000
    daily_cost_micro: int | None = None
    input_price: Decimal | None = None
    output_price: Decimal | None = None
    model_enabled: bool = True

    @classmethod
    def from_env(cls):
        """功能：加载后端配额；positive_integer/decimal_setting 校验配置，金额上限必须配套两项模型单价。"""
        input_price = decimal_setting("INPUT_PRICE_PER_MILLION")
        output_price = decimal_setting("OUTPUT_PRICE_PER_MILLION")
        cost = decimal_setting("DEMO_DAILY_COST_LIMIT")
        if (input_price is None) != (output_price is None):
            raise ValueError("模型输入与输出单价需要同时配置")
        if cost is not None and (cost <= 0 or input_price is None):
            raise ValueError("金额上限必须大于零，并配置输入与输出单价")
        enabled = os.getenv("DEMO_MODEL_ENABLED", "true").lower()
        if enabled not in {"true", "false"}:
            raise ValueError("DEMO_MODEL_ENABLED 必须为 true 或 false")
        return cls(
            concurrent=positive_integer("DEMO_MAX_CONCURRENT", 2),
            per_minute=positive_integer("DEMO_USER_RUNS_PER_MINUTE", 6),
            user_daily_tokens=positive_integer("DEMO_USER_DAILY_TOKENS", 100_000),
            daily_tokens=positive_integer("DEMO_DAILY_TOKENS", 500_000),
            daily_cost_micro=None if cost is None else micro_amount(cost * 1_000_000),
            input_price=input_price,
            output_price=output_price,
            model_enabled=enabled == "true",
        )

    def reserve_cost(self, tokens):
        """功能：按较高单价预留本轮费用；max 选单价，micro_amount 向上取整，未知单价不伪造金额。"""
        if self.input_price is None:
            return 0
        return micro_amount(Decimal(tokens) * max(self.input_price, self.output_price))


def acquire(policy, user_id, request_id, db_path, token_budget, lease_seconds):
    """功能：事务内取得执行席位并预留日预算；connect/execute 串行检查请求、账号频率、并发、Token 和金额，uuid4 生成租约。"""
    current = time.time()
    day = datetime.fromtimestamp(current, UTC).date().isoformat()
    tomorrow = (math.floor(current / 86400) + 1) * 86400
    cost = policy.reserve_cost(token_budget)
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        request = db.execute(
            "SELECT status FROM requests WHERE request_id=? AND user_id=?",
            (request_id, user_id),
        ).fetchone()
        if not request:
            raise PermissionError("资源不存在或无权访问")
        if request["status"] == "done":
            return None
        if request["status"] == "abandoned":
            raise ValueError("原请求已结束")
        if not policy.model_enabled:
            raise LimitReached(
                "MODEL_PAUSED", "演示站的智能对话暂时关闭，仍可使用工单表单。"
            )
        # 过期席位不再阻塞并发；已预留的费用和 Token 保留，避免崩溃后低估未知用量。
        active = db.execute(
            "SELECT user_id,expires_at FROM model_admissions WHERE state='active' AND expires_at>?",
            (current,),
        ).fetchall()
        own = [row for row in active if row["user_id"] == user_id]
        if own or len(active) >= policy.concurrent:
            retry = min(row["expires_at"] for row in (own or active)) - current
            raise LimitReached(
                "MODEL_BUSY", "已有对话正在处理，请稍后继续原请求。", min(retry, 15)
            )
        recent = db.execute(
            "SELECT count(*),min(started_at) FROM model_admissions WHERE user_id=? AND started_at>?",
            (user_id, current - 60),
        ).fetchone()
        if recent[0] >= policy.per_minute:
            raise LimitReached(
                "MODEL_RATE_LIMITED",
                "智能对话请求过于频繁，请稍后继续原请求。",
                recent[1] + 60 - current,
            )
        total = db.execute(
            """SELECT coalesce(sum(charged_tokens),0),coalesce(sum(charged_cost_micro),0),
            coalesce(sum(CASE WHEN user_id=? THEN charged_tokens ELSE 0 END),0)
            FROM model_admissions WHERE day=?""",
            (user_id, day),
        ).fetchone()
        if (
            total[0] + token_budget > policy.daily_tokens
            or total[2] + token_budget > policy.user_daily_tokens
        ):
            raise LimitReached(
                "TOKEN_QUOTA",
                "今天的智能对话额度不足，仍可使用工单表单。",
                tomorrow - current,
            )
        if (
            policy.daily_cost_micro is not None
            and total[1] + cost > policy.daily_cost_micro
        ):
            raise LimitReached(
                "COST_QUOTA",
                "演示站今日模型预算已用完，仍可使用工单表单。",
                tomorrow - current,
            )
        identifier = str(uuid4())
        db.execute(
            """INSERT INTO model_admissions
            (admission_id,request_id,user_id,day,started_at,expires_at,reserved_tokens,
            charged_tokens,reserved_cost_micro,charged_cost_micro,state)
            VALUES (?,?,?,?,?,?,?,?,?,?,'active')""",
            (
                identifier,
                request_id,
                user_id,
                day,
                current,
                current + lease_seconds,
                token_budget,
                token_budget,
                cost,
                cost,
            ),
        )
    return identifier


def settle(identifier, policy, previous, current, db_path):
    """功能：释放席位并结算本次增量；未知或估算用量保留预留值，已知 usage 用差值避免重试重复计费；事务使重复结算无效。"""
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM model_admissions WHERE admission_id=? AND state='active'",
            (identifier,),
        ).fetchone()
        if not row:
            return
        tokens, cost = row["reserved_tokens"], row["reserved_cost_micro"]
        if current is not None and previous is not None:
            delta = max(
                0, current.get("total_tokens", 0) - previous.get("total_tokens", 0)
            )
            tokens = max(tokens, delta) if current.get("estimated_tokens") else delta
            if policy.input_price is not None:
                if current.get("estimated_tokens"):
                    cost = max(cost, policy.reserve_cost(tokens))
                else:
                    cost = micro_amount(
                        Decimal(
                            max(
                                0,
                                current.get("input_tokens", 0)
                                - previous.get("input_tokens", 0),
                            )
                        )
                        * policy.input_price
                        + Decimal(
                            max(
                                0,
                                current.get("output_tokens", 0)
                                - previous.get("output_tokens", 0),
                            )
                        )
                        * policy.output_price
                    )
        db.execute(
            "UPDATE model_admissions SET state='finished',charged_tokens=?,charged_cost_micro=? WHERE admission_id=?",
            (tokens, cost, identifier),
        )


def overview(policy, db_path):
    """功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。"""
    current = time.time()
    day = datetime.fromtimestamp(current, UTC).date().isoformat()
    with storage.connect(db_path) as db:
        row = db.execute(
            "SELECT coalesce(sum(charged_tokens),0),coalesce(sum(charged_cost_micro),0),count(*) FROM model_admissions WHERE day=?",
            (day,),
        ).fetchone()
        active = db.execute(
            "SELECT count(*) FROM model_admissions WHERE state='active' AND expires_at>?",
            (current,),
        ).fetchone()[0]
    return {
        "day_utc": day,
        "runs": row[2],
        "active": active,
        "charged_or_reserved_tokens": row[0],
        "daily_token_limit": policy.daily_tokens,
        "charged_or_reserved_cost": None
        if policy.input_price is None
        else row[1] / 1_000_000,
        "daily_cost_limit": None
        if policy.daily_cost_micro is None
        else policy.daily_cost_micro / 1_000_000,
        "model_enabled": policy.model_enabled,
    }
