"""HTTP 入口：Cookie 登录、CSRF、授权接口；业务规则继续由 actions/service 执行。"""

import asyncio
import hashlib
import hmac
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from react_agent import actions, auth, quotas, service, sessions, storage
from react_agent.context import Context

COOKIE = "ticket_session"
WEB = Path(__file__).with_name("web")
LOG = logging.getLogger("uvicorn.error.ticket_http")
ALLOWED_FIELDS = {
    "create_ticket": {
        "product_model",
        "issue_description",
        "contact",
        "device_info",
        "impact",
    },
    "update_ticket_status": {"ticket_id", "new_status", "note"},
    "supplement_ticket": {"ticket_id", "description", "contact", "device_info"},
    "cancel_ticket": {"ticket_id", "note"},
    "assign_ticket": {"ticket_id", "assignee_id", "note"},
    "set_ticket_priority": {"ticket_id", "priority", "note"},
    "handoff_ticket": {"ticket_id", "note"},
}


class Body(BaseModel):
    """请求模型基类；ConfigDict 拒绝多余字段，防止把身份或确认参数偷偷传入。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Body):
    """账号和密码格式；密码保留原始空格，Field 限制长度以约束密码派生开销。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    user_id: str = Field(pattern=r"^[A-Za-z0-9_-]{3,40}$")
    password: str = Field(min_length=8, max_length=128)


class Staff(Credentials):
    """管理员创建人员；角色仍由服务端核验，不因请求填写 admin 就放行。"""

    role: Literal["customer", "technician", "support", "admin"] = "customer"
    models: list[str] = Field(default_factory=list, max_length=50)
    specialties: list[str] = Field(default_factory=list, max_length=20)


class Message(Body):
    """一条用户消息；Field 校验长度，身份由 Cookie 恢复。"""

    text: str = Field(min_length=1, max_length=4000)


class Proposal(Body):
    """手工操作提案；只允许白名单动作及其文本参数。"""

    action: str = Field(max_length=40)
    payload: dict[str, str]

    @model_validator(mode="after")
    def validate_payload(self):
        """功能：拒绝身份、版本等非业务字段；调用 set 检查白名单，len 检查字段长度。"""
        if (
            self.action not in ALLOWED_FIELDS
            or set(self.payload) - ALLOWED_FIELDS[self.action]
        ):
            raise ValueError("操作或字段不允许")
        if any(len(value) > 2000 for value in self.payload.values()):
            raise ValueError("单个操作字段最多 2000 字")
        return self


class Confirmation(Body):
    """确认只接收操作归属和用户决定，操作参数继续读取服务器冻结记录。"""

    thread_id: str = Field(min_length=1, max_length=64)
    accept_duplicate: bool = False
    cancel: bool = False


def csrf_for(token):
    """功能：从高随机会话令牌派生 CSRF 证明；调用 SHA256/encode，浏览器只取得证明而非 HttpOnly 令牌。"""
    return hashlib.sha256(("ticket-csrf:" + token).encode()).hexdigest()


def proposal_display(action, payload):
    """功能：把表单变成可读记录；字典翻译动作和字段，join 拼接填写内容，不显示内部 JSON。"""
    names = {
        "create_ticket": "创建工单",
        "update_ticket_status": "更新状态",
        "supplement_ticket": "补充信息",
        "cancel_ticket": "取消工单",
        "assign_ticket": "分派维修人员",
        "set_ticket_priority": "调整优先级",
        "handoff_ticket": "转人工",
    }
    fields = {
        "product_model": "设备型号",
        "issue_description": "故障描述",
        "contact": "联系方式",
        "device_info": "设备信息",
        "ticket_id": "工单编号",
        "new_status": "目标状态",
        "note": "处理说明",
        "description": "补充描述",
        "assignee_id": "维修账号",
        "priority": "优先级",
    }
    return (
        names[action]
        + "\n"
        + "\n".join(
            f"{fields[key]}：{value}"
            for key, value in payload.items()
            if value and key in fields
        )
    )


def public_request(row):
    """功能：挑选用户可见请求字段；dict.get 读取结果，省略原始模型消息及执行租约。"""
    output = row["output"] or {}
    return {
        "request_id": row["request_id"],
        "thread_id": row["thread_id"],
        "status": row["status"],
        "answer": output.get("answer", ""),
        "success": output.get("success"),
        "error_code": output.get("error_code"),
        "usage": output.get("usage", {}),
    }


def business_response(outcome):
    """功能：保留业务结果并选择 HTTP 状态；JSONResponse 序列化，result 错误仍来自业务层。"""
    if outcome.get("success"):
        return outcome
    code = outcome.get("error_code", "")
    status = (
        403
        if code == "FORBIDDEN"
        else 404
        if code == "NOT_FOUND"
        else 503
        if code == "DATABASE_BUSY"
        else 409
    )
    return JSONResponse(outcome, status_code=status)


def create_app(db_path=None, *, origin=None, secure=None):
    """功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。"""
    load_dotenv(storage.ROOT / ".env")
    policy = quotas.DemoLimits.from_env()
    db_path = str(storage.database_path(db_path))
    origin = (origin or os.getenv("APP_ORIGIN", "http://127.0.0.1:8000")).rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        raise ValueError("APP_ORIGIN 必须是包含协议的站点地址，不含路径或凭据")
    secure = parsed.scheme == "https" if secure is None else secure
    if (parsed.scheme == "https" and not secure) or (
        not secure
        and parsed.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}
    ):
        raise ValueError("非本机部署必须配置 HTTPS 与 Secure Cookie")

    @asynccontextmanager
    async def lifespan(app):
        """功能：启动时初始化数据库；run_in_threadpool 执行 connect，退出时无需留下后台模型任务。"""

        def initialize():
            """功能：通过 connect 进行兼容迁移，连接离开 with 后关闭。"""
            with storage.connect(db_path):
                pass

        await run_in_threadpool(initialize)
        yield

    app = FastAPI(
        title="售后工单服务",
        version="0.4.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.db_path = db_path
    app.state.model_limits = policy
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[parsed.hostname])

    @app.middleware("http")
    async def request_log(request, call_next):
        """功能：给响应加防护头并记录耗时；uuid4 标识请求，call_next 执行路由，日志不包含凭据/正文/查询参数。"""
        started, trace = time.monotonic(), str(uuid4())
        try:
            response = await call_next(request)
        except Exception as error:
            # 只记录异常类型，避免异常文本包含 SQL、凭据或客户原文。
            LOG.error(
                storage.encode(
                    {"request_id": trace, "error_type": type(error).__name__}
                )
            )
            response = JSONResponse(
                {
                    "success": False,
                    "error_code": "INTERNAL_ERROR",
                    "message": "服务暂时无法完成请求，请保留原请求编号后重试。",
                },
                status_code=500,
            )
        response.headers["X-Request-ID"] = trace
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith(("/docs", "/openapi")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        route = getattr(request.scope.get("route"), "path", "unmatched")
        LOG.info(
            storage.encode(
                {
                    "request_id": trace,
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        """功能：统一 HTTP 错误；JSONResponse 返回受控说明，不回传堆栈。"""
        return JSONResponse(
            {
                "success": False,
                "error_code": f"HTTP_{error.status_code}",
                "message": str(error.detail),
            },
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        """功能：隐藏验证异常里的原始输入；只读取 errors 的位置字段，避免密码被响应或日志回显。"""
        return JSONResponse(
            {
                "success": False,
                "error_code": "INVALID_FIELDS",
                "message": "请求参数格式不正确。",
                "fields": [list(item["loc"]) for item in error.errors()],
            },
            status_code=422,
        )

    @app.exception_handler(PermissionError)
    async def denied(request, error):
        """功能：隐藏跨用户资源存在性；JSONResponse 返回统一拒绝结果。"""
        return JSONResponse(
            {
                "success": False,
                "error_code": "FORBIDDEN",
                "message": "资源不存在或无权访问。",
            },
            status_code=403,
        )

    @app.exception_handler(quotas.LimitReached)
    async def model_limit(request, error):
        """功能：向浏览器说明模型限额；JSONResponse 返回 429 与 Retry-After，原请求保留供稍后重试。"""
        return JSONResponse(
            {"success": False, "error_code": error.code, "message": str(error)},
            status_code=429,
            headers={"Retry-After": str(error.retry_after)},
        )

    @app.exception_handler(ValueError)
    async def conflict(request, error):
        """功能：把业务冲突转为可处理响应；str 仅用于业务层受控异常。"""
        return JSONResponse(
            {"success": False, "error_code": "CONFLICT", "message": str(error)},
            status_code=409,
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def database_busy(request, error):
        """功能：数据库错误返回可重试状态；JSONResponse 隐藏路径/SQL，Retry-After 提示稍后再试。"""
        return JSONResponse(
            {
                "success": False,
                "error_code": "DATABASE_BUSY",
                "message": "数据库暂不可用，请稍后重试原请求。",
            },
            status_code=503,
            headers={"Retry-After": "1"},
        )

    def same_origin(
        request: Request,
        origin_header: Annotated[str | None, Header(alias="Origin")] = None,
    ):
        """功能：阻止跨站修改和登录 CSRF；比较 Origin 与显式配置站点，拒绝缺失或不匹配来源。"""
        if origin_header != origin:
            raise HTTPException(403, "请求来源不匹配")

    def current_user(request: Request):
        """功能：从 Cookie 恢复身份；调用 authenticate 查有效期及数据库真实角色，忽略 URL/正文里的身份。"""
        user = auth.authenticate(request.cookies.get(COOKIE, ""), db_path)
        if not user:
            raise HTTPException(401, "请先登录")
        return user

    def write_user(
        request: Request,
        user=Depends(current_user),
        source=Depends(same_origin),
        csrf_header: Annotated[
            str | None, Header(alias="X-CSRF-Token", max_length=128)
        ] = None,
    ):
        """功能：写操作额外验证 CSRF；csrf_for 派生证明、compare_digest 恒定时间比较，current_user 已认证。"""
        supplied = csrf_header or ""
        if not hmac.compare_digest(supplied, csrf_for(request.cookies[COOKIE])):
            raise HTTPException(403, "操作验证已失效，请刷新页面")
        return user

    def context_for(user, thread_id, request_id=""):
        """功能：创建可信业务上下文；get_thread 检查会话归属，Context 注入身份/数据库，用户不能指定角色。"""
        sessions.get_thread(thread_id, user["user_id"], db_path)
        return Context(
            user_id=user["user_id"],
            thread_id=thread_id,
            request_id=request_id,
            db_path=db_path,
        )

    User = Annotated[dict, Depends(current_user)]
    Writer = Annotated[dict, Depends(write_user)]
    SubmissionKey = Annotated[
        str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9_-]{8,128}$")
    ]

    @app.get("/health/live")
    def live():
        """功能：检查进程可响应；返回常量，不访问模型或数据库。"""
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        """功能：检查数据库可读；connect/execute 读取 users，和模型可用性分别报告。"""
        with storage.connect(db_path) as db:
            db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return {"status": "ready"}

    @app.post("/api/login", dependencies=[Depends(same_origin)])
    def login(body: Credentials, request: Request, response: Response):
        """功能：限流登录并设置 HttpOnly Cookie；auth.login 校验账号，logout 撤销旧令牌，set_cookie 保存新会话。"""
        outcome = auth.login(
            body.user_id,
            body.password,
            db_path,
            client_key=request.client.host if request.client else "unknown",
        )
        if not outcome["success"]:
            raise HTTPException(
                429 if outcome["error_code"] == "RATE_LIMITED" else 401,
                outcome["message"],
            )
        if old := request.cookies.get(COOKIE):
            auth.logout(old, db_path)
        response.set_cookie(
            COOKIE,
            outcome["token"],
            max_age=43200,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )
        return {"user": outcome["user"], "csrf_token": csrf_for(outcome["token"])}

    @app.get("/api/session")
    def session(request: Request, user: User):
        """功能：刷新后恢复身份和 CSRF 证明；调用 csrf_for，绝不返回原始会话令牌。"""
        return {"user": user, "csrf_token": csrf_for(request.cookies[COOKIE])}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, user: Writer):
        """功能：撤销会话并移除浏览器 Cookie；调用 auth.logout/delete_cookie，保留业务记录。"""
        auth.logout(request.cookies[COOKIE], db_path)
        response.delete_cookie(
            COOKIE, path="/", httponly=True, secure=secure, samesite="lax"
        )
        return {"success": True}

    @app.get("/api/threads")
    def threads(user: User):
        """功能：列出本人会话；调用 list_threads，身份由认证依赖提供。"""
        return {"threads": sessions.list_threads(user["user_id"], db_path)}

    @app.post("/api/threads", status_code=201)
    def new_thread(user: Writer):
        """功能：创建本人新会话；create_thread 生成 UUID 并持久保存。"""
        return {"thread_id": sessions.create_thread(user["user_id"], db_path)}

    @app.get("/api/threads/{thread_id}")
    def thread(thread_id: str, user: User):
        """功能：恢复对话和待处理状态；get_thread 验权，active_request/public_request 返回可重试请求，pending_actions 取有效卡片。"""
        context = context_for(user, thread_id)
        row = sessions.get_thread(thread_id, user["user_id"], db_path)
        active = sessions.active_request(thread_id, user["user_id"], db_path)
        return {
            "thread_id": thread_id,
            "transcript": row["transcript"],
            "memory": row["memory"],
            "active_request": public_request(active) if active else None,
            "pending_actions": actions.pending_actions(context),
        }

    @app.post("/api/threads/{thread_id}/requests", status_code=202)
    def submit_message(
        thread_id: str, body: Message, user: Writer, idempotency_key: SubmissionKey
    ):
        """功能：先持久化消息而不调用模型；begin_request 将幂等键与请求原子保存，get_request/public_request 返回恢复入口。"""
        rid = sessions.begin_request(
            thread_id, user["user_id"], body.text, db_path, client_key=idempotency_key
        )
        return public_request(sessions.get_request(rid, user["user_id"], db_path))

    @app.get("/api/requests/{request_id}")
    def request_status(request_id: str, user: User):
        """功能：查询本人请求进度；get_request 检查归属，public_request 隐去内部运行字段。"""
        return public_request(
            sessions.get_request(request_id, user["user_id"], db_path)
        )

    @app.post("/api/requests/{request_id}/run")
    async def run(request_id: str, user: Writer):
        """功能：限额内执行原请求；acquire 先预留，usage_for 读取累计用量，run_request 恢复图，settle 结算增量，shield 保护取消时的清理。"""
        row = await run_in_threadpool(
            sessions.get_request, request_id, user["user_id"], db_path
        )
        if row["status"] == "abandoned":
            raise HTTPException(409, "该请求已结束，请提交新消息")
        if row["status"] == "done":
            return public_request(row)
        context = Context()
        key = (
            "DEEPSEEK_API_KEY"
            if context.model.startswith("deepseek/")
            else "OPENAI_API_KEY"
        )
        if not os.getenv(key, "").strip():
            raise HTTPException(503, "模型尚未配置，仍可使用工单表单")
        admission = await run_in_threadpool(
            quotas.acquire,
            policy,
            user["user_id"],
            request_id,
            db_path,
            context.max_tokens,
            context.execution_timeout + 60,
        )
        if admission is not None:
            previous, current = None, None
            try:
                events = await run_in_threadpool(
                    sessions.timeline, row["thread_id"], user["user_id"], db_path
                )
                previous = service.usage_for(
                    [event for event in events if event["request_id"] == request_id]
                )
                output = await service.run_request(request_id, user["user_id"], db_path)
                current = output.get("usage")
            finally:
                # 即使浏览器断开也尝试释放席位；进程直接退出时，租约到期释放，预算保守保留。
                await asyncio.shield(
                    run_in_threadpool(
                        quotas.settle, admission, policy, previous, current, db_path
                    )
                )
        row = await run_in_threadpool(
            sessions.get_request, request_id, user["user_id"], db_path
        )
        return public_request(row)

    @app.post("/api/requests/{request_id}/abandon")
    def abandon(request_id: str, user: Writer):
        """功能：结束未完成请求；get_request 验权，abandon_request 拒绝仍持有活动租约的请求。"""
        sessions.get_request(request_id, user["user_id"], db_path)
        if not sessions.abandon_request(request_id, user["user_id"], db_path):
            raise HTTPException(409, "请求仍在执行，请稍后重试")
        return {"success": True}

    @app.post("/api/threads/{thread_id}/proposals")
    def proposal(
        thread_id: str, body: Proposal, user: Writer, idempotency_key: SubmissionKey
    ):
        """功能：表单提出操作；begin_request/claim_request 识别重试，propose 冻结参数，finish_request 保存结果；实际写工单留给确认接口。"""
        text = "工单操作：" + storage.encode(body.model_dump())
        rid = sessions.begin_request(
            thread_id,
            user["user_id"],
            text,
            db_path,
            client_key=idempotency_key,
            display_text=proposal_display(body.action, body.payload),
        )
        row = sessions.get_request(rid, user["user_id"], db_path)
        if row["status"] == "done":
            return business_response(row["output"])
        if row["status"] == "abandoned":
            raise HTTPException(409, "原请求已结束，请重新提交")
        token = sessions.claim_request(rid, user["user_id"], db_path)
        if token is None:
            return business_response(
                sessions.get_request(rid, user["user_id"], db_path)["output"]
            )
        context = context_for(user, thread_id, rid)
        outcome = actions.propose(context, body.action, body.payload)
        outcome["request_id"] = rid
        outcome["answer"] = actions.render_result(outcome)
        sessions.finish_request(rid, user["user_id"], token, outcome, db_path)
        return business_response(outcome)

    @app.post("/api/operations/{operation_id}/confirm")
    def confirm(operation_id: str, body: Confirmation, user: Writer):
        """功能：确认服务器已有提案；context_for 验会话，confirm_action 事务内校验权限/版本/幂等并执行。"""
        return business_response(
            actions.confirm_action(
                context_for(user, body.thread_id),
                operation_id,
                accept_duplicate=body.accept_duplicate,
                cancel=body.cancel,
            )
        )

    @app.get("/api/tickets")
    def tickets(
        thread_id: str,
        user: User,
        status: str = "",
        product_model: str = "",
        ticket_id: str = "",
    ):
        """功能：按身份筛选工单；context_for 校验会话，search_tickets 实施可见性与数量限制。"""
        return business_response(
            actions.search_tickets(
                context_for(user, thread_id),
                status=status,
                product_model=product_model,
                ticket_id=ticket_id,
            )
        )

    @app.get("/api/tickets/{ticket_id}")
    def ticket(ticket_id: str, thread_id: str, user: User):
        """功能：读取工单与审计；context_for 验会话，read_ticket(history=True) 校验归属并返回历史。"""
        return business_response(
            actions.read_ticket(context_for(user, thread_id), ticket_id, history=True)
        )

    @app.get("/api/admin/users")
    def users(user: User):
        """功能：管理员查看人员；核对真实 role 后调用 auth.users，返回值不含密码散列。"""
        if user["role"] != "admin":
            raise HTTPException(403, "需要管理员权限")
        return {"users": auth.users(db_path)}

    @app.post("/api/admin/users")
    def create_user(body: Staff, user: Writer):
        """功能：管理员添加人员；再次核验角色，create_user 保存密码散列和专长，不开放远程首次管理员抢注。"""
        if user["role"] != "admin":
            raise HTTPException(403, "需要管理员权限")
        return business_response(
            auth.create_user(
                body.user_id,
                body.password,
                body.role,
                db_path,
                administrator=user["user_id"],
                models=body.models,
                specialties=body.specialties,
            )
        )

    @app.get("/api/admin/metrics")
    def metrics(user: User):
        """功能：提供管理员计数；connect/execute 聚合请求与工单，overview 汇总当天模型预留及结算额度，不返回客户正文。"""
        if user["role"] != "admin":
            raise HTTPException(403, "需要管理员权限")
        with storage.connect(db_path) as db:
            statuses = {
                row[0]: row[1]
                for row in db.execute(
                    "SELECT status,count(*) FROM requests GROUP BY status"
                )
            }
            count = db.execute("SELECT count(*) FROM tickets").fetchone()[0]
        return {
            "requests": statuses,
            "tickets": count,
            "model_budget": quotas.overview(policy, db_path),
        }

    @app.get("/", include_in_schema=False)
    def index():
        """功能：打开浏览器工作台；FileResponse 返回静态 HTML，页面通过同源 API 获取业务数据。"""
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
