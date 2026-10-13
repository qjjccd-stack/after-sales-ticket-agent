# HTTP 与运维函数讲解（v4）

更新时间：2026-10-10。先读 api 的认证依赖，再读消息提交/执行/确认三条路径，最后读备份与压测。以下均对应当前源码；旧业务层的细粒度说明仍见 [原业务函数讲解](functions.md)。

HTTP 的 `create_app` 内部函数由 FastAPI 注册后在请求到来时调用；`Depends` 负责先执行身份/CSRF 依赖。测试函数的参数由 pytest 夹具提供。

## src/react_agent/api.py

### `Proposal.validate_payload()`

[查看源码](../src/react_agent/api.py#L83)

功能：拒绝身份、版本等非业务字段；调用 set 检查白名单，len 检查字段长度。

| 调用 | 作用 |
|---|---|
| `set` | 计算去重集合或检查未知字段。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `any` | 判断是否存在非法字段。 |
| `len` | 检查数量或长度限制。 |
| `self.payload.values` | 遍历字典中的所有值。 |

### `csrf_for()`

[查看源码](../src/react_agent/api.py#L103)

功能：从高随机会话令牌派生 CSRF 证明；调用 SHA256/encode，浏览器只取得证明而非 HttpOnly 令牌。

| 调用 | 作用 |
|---|---|
| `hashlib.sha256(('ticket-csrf:' + token).encode()).hexdigest` | 把摘要转换为十六进制字符串。 |
| `hashlib.sha256` | 计算不可逆 SHA256 指纹，用于 CSRF 派生、限流键或快照校验。 |
| `('ticket-csrf:' + token).encode` | 将字符串按默认 UTF-8 编码成字节。 |

### `proposal_display()`

[查看源码](../src/react_agent/api.py#L108)

功能：把表单变成可读记录；字典翻译动作和字段，join 拼接填写内容，不显示内部 JSON。

| 调用 | 作用 |
|---|---|
| `'\n'.join` | 拼接可读文案；不用于拼接未经校验的 SQL 值。 |
| `payload.items` | 遍历字段与值。 |

### `public_request()`

[查看源码](../src/react_agent/api.py#L142)

功能：挑选用户可见请求字段；dict.get 读取结果，省略原始模型消息及执行租约。

| 调用 | 作用 |
|---|---|
| `output.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |

### `business_response()`

[查看源码](../src/react_agent/api.py#L156)

功能：保留业务结果并选择 HTTP 状态；JSONResponse 序列化，result 错误仍来自业务层。

| 调用 | 作用 |
|---|---|
| `outcome.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |

### `create_app()`

[查看源码](../src/react_agent/api.py#L173)

功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。

| 调用 | 作用 |
|---|---|
| `load_dotenv` | 从配置文件补充尚未设置的环境变量，不覆盖进程已指定的值。 |
| `quotas.DemoLimits.from_env` | 功能：加载后端配额；positive_integer/decimal_setting 校验配置，金额上限必须配套两项模型单价。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `storage.database_path` | 调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。 |
| `(origin or os.getenv('APP_ORIGIN', 'http://127.0.0.1:8000')).rstrip` | 去掉地址末尾的斜线后做精确匹配。 |
| `os.getenv` | 读取环境配置，默认值用于本机启动。 |
| `urlsplit` | 解析站点协议/主机/路径并验证配置。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `FastAPI` | 创建路由、依赖、异常处理与生命周期的 HTTP 应用。 |
| `app.add_middleware` | 安装 Host 白名单等中间件。 |
| `Depends` | 注册认证、同源和 CSRF 等依赖，FastAPI 先执行依赖再进入业务路由。 |
| `Header` | 声明需要的 HTTP 请求头及格式限制，同时生成接口文档。 |
| `app.mount` | 把静态资源应用挂到指定 URL 前缀。 |
| `StaticFiles` | 提供 CSS/JavaScript 静态资源；不暴露项目其他文件。 |

### `create_app.lifespan()`

[查看源码](../src/react_agent/api.py#L197)

功能：启动时初始化数据库；run_in_threadpool 执行 connect，退出时无需留下后台模型任务。

| 调用 | 作用 |
|---|---|
| `run_in_threadpool` | 在线程池执行同步数据库代码，避免阻塞异步服务循环。 |

### `create_app.lifespan.initialize()`

[查看源码](../src/react_agent/api.py#L200)

功能：通过 connect 进行兼容迁移，连接离开 with 后关闭。

| 调用 | 作用 |
|---|---|
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |

### `create_app.request_log()`

[查看源码](../src/react_agent/api.py#L220)

功能：给响应加防护头并记录耗时；uuid4 标识请求，call_next 执行路由，日志不包含凭据/正文/查询参数。

| 调用 | 作用 |
|---|---|
| `time.monotonic` | 用单调时钟计算 HTTP 处理耗时。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `uuid4` | 生成一次请求或客户端提交的随机编号。 |
| `call_next` | 执行后续 HTTP 中间件和路由，取得响应。 |
| `LOG.error` | 输出受控异常类别或 CLI 参数错误，不打印密码。 |
| `storage.encode` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `type` | 读取异常类型名称，避免输出异常中的私人文本。 |
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |
| `request.url.path.startswith` | 判断地址或模型名是否具有指定前缀。 |
| `getattr` | 读取可选属性或路由模板，不依赖私有字段必须存在。 |
| `request.scope.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `LOG.info` | 输出不含正文或凭据的结构化 HTTP 统计。 |
| `round` | 控制统计数值的小数位。 |

### `create_app.http_error()`

[查看源码](../src/react_agent/api.py#L265)

功能：统一 HTTP 错误；JSONResponse 返回受控说明，不回传堆栈。

| 调用 | 作用 |
|---|---|
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |
| `str` | 将路径、编号或受控错误转换为文本。 |

### `create_app.validation_error()`

[查看源码](../src/react_agent/api.py#L278)

功能：隐藏验证异常里的原始输入；只读取 errors 的位置字段，避免密码被响应或日志回显。

| 调用 | 作用 |
|---|---|
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |
| `list` | 展开迭代结果。 |
| `error.errors` | 读取校验异常列表；API 仅挑选字段位置，不回显输入。 |

### `create_app.denied()`

[查看源码](../src/react_agent/api.py#L291)

功能：隐藏跨用户资源存在性；JSONResponse 返回统一拒绝结果。

| 调用 | 作用 |
|---|---|
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |

### `create_app.model_limit()`

[查看源码](../src/react_agent/api.py#L303)

功能：向浏览器说明模型限额；JSONResponse 返回 429 与 Retry-After，原请求保留供稍后重试。

| 调用 | 作用 |
|---|---|
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |
| `str` | 将路径、编号或受控错误转换为文本。 |

### `create_app.conflict()`

[查看源码](../src/react_agent/api.py#L312)

功能：把业务冲突转为可处理响应；str 仅用于业务层受控异常。

| 调用 | 作用 |
|---|---|
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |
| `str` | 将路径、编号或受控错误转换为文本。 |

### `create_app.database_busy()`

[查看源码](../src/react_agent/api.py#L320)

功能：数据库错误返回可重试状态；JSONResponse 隐藏路径/SQL，Retry-After 提示稍后再试。

| 调用 | 作用 |
|---|---|
| `JSONResponse` | 序列化结构化响应并设置 HTTP 状态/响应头。 |

### `create_app.same_origin()`

[查看源码](../src/react_agent/api.py#L332)

功能：阻止跨站修改和登录 CSRF；比较 Origin 与显式配置站点，拒绝缺失或不匹配来源。

| 调用 | 作用 |
|---|---|
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |

### `create_app.current_user()`

[查看源码](../src/react_agent/api.py#L340)

功能：从 Cookie 恢复身份；调用 authenticate 查有效期及数据库真实角色，忽略 URL/正文里的身份。

| 调用 | 作用 |
|---|---|
| `auth.authenticate` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |
| `request.cookies.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |

### `create_app.write_user()`

[查看源码](../src/react_agent/api.py#L347)

功能：写操作额外验证 CSRF；csrf_for 派生证明、compare_digest 恒定时间比较，current_user 已认证。

| 调用 | 作用 |
|---|---|
| `hmac.compare_digest` | 以恒定时间方式比较令牌证明，避免普通比较的时序差异。 |
| `csrf_for` | 功能：从高随机会话令牌派生 CSRF 证明；调用 SHA256/encode，浏览器只取得证明而非 HttpOnly 令牌。 |
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |

### `create_app.context_for()`

[查看源码](../src/react_agent/api.py#L361)

功能：创建可信业务上下文；get_thread 检查会话归属，Context 注入身份/数据库，用户不能指定角色。

| 调用 | 作用 |
|---|---|
| `sessions.get_thread` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `Context` | 构造服务端运行上下文，包含真实用户、会话、请求和数据库位置。 |

### `create_app.live()`

[查看源码](../src/react_agent/api.py#L378)

功能：检查进程可响应；返回常量，不访问模型或数据库。

### `create_app.ready()`

[查看源码](../src/react_agent/api.py#L383)

功能：检查数据库可读；connect/execute 读取 users，和模型可用性分别报告。

| 调用 | 作用 |
|---|---|
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute('SELECT 1 FROM users LIMIT 1').fetchone` | 读取一行数据库结果。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |

### `create_app.login()`

[查看源码](../src/react_agent/api.py#L390)

功能：限流登录并设置 HttpOnly Cookie；auth.login 校验账号，logout 撤销旧令牌，set_cookie 保存新会话。

| 调用 | 作用 |
|---|---|
| `auth.login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |
| `request.cookies.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `auth.logout` | 调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。 |
| `response.set_cookie` | 向浏览器设置 HttpOnly/SameSite/Secure 等会话属性。 |
| `csrf_for` | 功能：从高随机会话令牌派生 CSRF 证明；调用 SHA256/encode，浏览器只取得证明而非 HttpOnly 令牌。 |

### `create_app.session()`

[查看源码](../src/react_agent/api.py#L417)

功能：刷新后恢复身份和 CSRF 证明；调用 csrf_for，绝不返回原始会话令牌。

| 调用 | 作用 |
|---|---|
| `csrf_for` | 功能：从高随机会话令牌派生 CSRF 证明；调用 SHA256/encode，浏览器只取得证明而非 HttpOnly 令牌。 |

### `create_app.logout()`

[查看源码](../src/react_agent/api.py#L422)

功能：撤销会话并移除浏览器 Cookie；调用 auth.logout/delete_cookie，保留业务记录。

| 调用 | 作用 |
|---|---|
| `auth.logout` | 调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。 |
| `response.delete_cookie` | 通知浏览器移除同名 Cookie。 |

### `create_app.threads()`

[查看源码](../src/react_agent/api.py#L431)

功能：列出本人会话；调用 list_threads，身份由认证依赖提供。

| 调用 | 作用 |
|---|---|
| `sessions.list_threads` | 参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。 |

### `create_app.new_thread()`

[查看源码](../src/react_agent/api.py#L436)

功能：创建本人新会话；create_thread 生成 UUID 并持久保存。

| 调用 | 作用 |
|---|---|
| `sessions.create_thread` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |

### `create_app.thread()`

[查看源码](../src/react_agent/api.py#L441)

功能：恢复对话和待处理状态；get_thread 验权，active_request/public_request 返回可重试请求，pending_actions 取有效卡片。

| 调用 | 作用 |
|---|---|
| `context_for` | 功能：创建可信业务上下文；get_thread 检查会话归属，Context 注入身份/数据库，用户不能指定角色。 |
| `sessions.get_thread` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `sessions.active_request` | 查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。 |
| `public_request` | 功能：挑选用户可见请求字段；dict.get 读取结果，省略原始模型消息及执行租约。 |
| `actions.pending_actions` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |

### `create_app.submit_message()`

[查看源码](../src/react_agent/api.py#L455)

功能：先持久化消息而不调用模型；begin_request 将幂等键与请求原子保存，get_request/public_request 返回恢复入口。

| 调用 | 作用 |
|---|---|
| `sessions.begin_request` | 事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。 |
| `public_request` | 功能：挑选用户可见请求字段；dict.get 读取结果，省略原始模型消息及执行租约。 |
| `sessions.get_request` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |

### `create_app.request_status()`

[查看源码](../src/react_agent/api.py#L465)

功能：查询本人请求进度；get_request 检查归属，public_request 隐去内部运行字段。

| 调用 | 作用 |
|---|---|
| `public_request` | 功能：挑选用户可见请求字段；dict.get 读取结果，省略原始模型消息及执行租约。 |
| `sessions.get_request` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |

### `create_app.run()`

[查看源码](../src/react_agent/api.py#L472)

功能：限额内执行原请求；acquire 先预留，usage_for 读取累计用量，run_request 恢复图，settle 结算增量，shield 保护取消时的清理。

| 调用 | 作用 |
|---|---|
| `run_in_threadpool` | 在线程池执行同步数据库代码，避免阻塞异步服务循环。 |
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |
| `public_request` | 功能：挑选用户可见请求字段；dict.get 读取结果，省略原始模型消息及执行租约。 |
| `Context` | 构造服务端运行上下文，包含真实用户、会话、请求和数据库位置。 |
| `context.model.startswith` | 判断地址或模型名是否具有指定前缀。 |
| `os.getenv(key, '').strip` | 删除首尾空白，识别空消息或空配置。 |
| `os.getenv` | 读取环境配置，默认值用于本机启动。 |
| `service.usage_for` | 从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。 |
| `service.run_request` | claim_request 获取租约，用 aget_state 判断是否恢复检查点，astream 收集输出，finish_request 保存结果。 |
| `output.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `asyncio.shield` | 保护结算清理协程，使调用方取消时仍尝试释放席位；进程强杀则由持久租约过期兜底。 |

### `create_app.abandon()`

[查看源码](../src/react_agent/api.py#L522)

功能：结束未完成请求；get_request 验权，abandon_request 拒绝仍持有活动租约的请求。

| 调用 | 作用 |
|---|---|
| `sessions.get_request` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |
| `sessions.abandon_request` | 撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。 |
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |

### `create_app.proposal()`

[查看源码](../src/react_agent/api.py#L530)

功能：表单提出操作；begin_request/claim_request 识别重试，propose 冻结参数，finish_request 保存结果；实际写工单留给确认接口。

| 调用 | 作用 |
|---|---|
| `storage.encode` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `body.model_dump` | 把已验证的 Pydantic 请求转换成普通字典。 |
| `sessions.begin_request` | 事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。 |
| `proposal_display` | 功能：把表单变成可读记录；字典翻译动作和字段，join 拼接填写内容，不显示内部 JSON。 |
| `sessions.get_request` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |
| `business_response` | 功能：保留业务结果并选择 HTTP 状态；JSONResponse 序列化，result 错误仍来自业务层。 |
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |
| `sessions.claim_request` | BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。 |
| `context_for` | 功能：创建可信业务上下文；get_thread 检查会话归属，Context 注入身份/数据库，用户不能指定角色。 |
| `actions.propose` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |
| `actions.render_result` | 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。 |
| `sessions.finish_request` | 校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。 |

### `create_app.confirm()`

[查看源码](../src/react_agent/api.py#L561)

功能：确认服务器已有提案；context_for 验会话，confirm_action 事务内校验权限/版本/幂等并执行。

| 调用 | 作用 |
|---|---|
| `business_response` | 功能：保留业务结果并选择 HTTP 状态；JSONResponse 序列化，result 错误仍来自业务层。 |
| `actions.confirm_action` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `context_for` | 功能：创建可信业务上下文；get_thread 检查会话归属，Context 注入身份/数据库，用户不能指定角色。 |

### `create_app.tickets()`

[查看源码](../src/react_agent/api.py#L573)

功能：按身份筛选工单；context_for 校验会话，search_tickets 实施可见性与数量限制。

| 调用 | 作用 |
|---|---|
| `business_response` | 功能：保留业务结果并选择 HTTP 状态；JSONResponse 序列化，result 错误仍来自业务层。 |
| `actions.search_tickets` | 按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。 |
| `context_for` | 功能：创建可信业务上下文；get_thread 检查会话归属，Context 注入身份/数据库，用户不能指定角色。 |

### `create_app.ticket()`

[查看源码](../src/react_agent/api.py#L591)

功能：读取工单与审计；context_for 验会话，read_ticket(history=True) 校验归属并返回历史。

| 调用 | 作用 |
|---|---|
| `business_response` | 功能：保留业务结果并选择 HTTP 状态；JSONResponse 序列化，result 错误仍来自业务层。 |
| `actions.read_ticket` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |
| `context_for` | 功能：创建可信业务上下文；get_thread 检查会话归属，Context 注入身份/数据库，用户不能指定角色。 |

### `create_app.users()`

[查看源码](../src/react_agent/api.py#L598)

功能：管理员查看人员；核对真实 role 后调用 auth.users，返回值不含密码散列。

| 调用 | 作用 |
|---|---|
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |
| `auth.users` | 供可信工作台列举人员；调用 connect/public_user 去除认证资料。 |

### `create_app.create_user()`

[查看源码](../src/react_agent/api.py#L605)

功能：管理员添加人员；再次核验角色，create_user 保存密码散列和专长，不开放远程首次管理员抢注。

| 调用 | 作用 |
|---|---|
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |
| `business_response` | 功能：保留业务结果并选择 HTTP 状态；JSONResponse 序列化，result 错误仍来自业务层。 |
| `auth.create_user` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |

### `create_app.metrics()`

[查看源码](../src/react_agent/api.py#L622)

功能：提供管理员计数；connect/execute 聚合请求与工单，overview 汇总当天模型预留及结算额度，不返回客户正文。

| 调用 | 作用 |
|---|---|
| `HTTPException` | 中断当前请求，交给统一异常处理器返回受控错误。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute('SELECT count(*) FROM tickets').fetchone` | 读取一行数据库结果。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |

### `create_app.index()`

[查看源码](../src/react_agent/api.py#L641)

功能：打开浏览器工作台；FileResponse 返回静态 HTML，页面通过同源 API 获取业务数据。

| 调用 | 作用 |
|---|---|
| `FileResponse` | 返回本地 HTML 文件，由浏览器加载页面。 |

## scripts/db_admin.py

### `inspect_database()`

[查看源码](../scripts/db_admin.py#L15)

功能：只读检查快照；as_uri/connect 避免意外新建源库，quick_check 校验一致性，SELECT 验证应用表和版本。

| 调用 | 作用 |
|---|---|
| `Path(path).resolve` | 规范化路径；strict=True 确保源库已存在。 |
| `Path` | 构造本地路径。 |
| `sqlite3.connect` | 打开数据库连接；storage.connect 还负责迁移和提交/回滚，sqlite3.connect 是底层连接。 |
| `path.as_uri` | 把本地路径安全编码成 SQLite 只读 URI。 |
| `db.execute('PRAGMA quick_check').fetchone` | 读取一行数据库结果。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `db.execute('PRAGMA user_version').fetchone` | 读取一行数据库结果。 |
| `db.execute('SELECT count(*) FROM tickets').fetchone` | 读取一行数据库结果。 |
| `db.execute('SELECT count(*) FROM requests').fetchone` | 读取一行数据库结果。 |
| `db.close` | 关闭文件描述符或数据库连接，释放资源。 |

### `copy_database()`

[查看源码](../scripts/db_admin.py#L41)

功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。

| 调用 | 作用 |
|---|---|
| `Path(source).resolve` | 规范化路径；strict=True 确保源库已存在。 |
| `Path` | 构造本地路径。 |
| `Path(destination).resolve` | 规范化路径；strict=True 确保源库已存在。 |
| `inspect_database` | 功能：只读检查快照；as_uri/connect 避免意外新建源库，quick_check 校验一致性，SELECT 验证应用表和版本。 |
| `destination.exists` | 检查目标是否已存在，防止覆盖。 |
| `FileExistsError` | 拒绝覆盖已有目标。 |
| `destination.parent.mkdir` | 创建目标目录。 |
| `tempfile.mkstemp` | 排他创建仅当前用户可读写的临时文件。 |
| `os.close` | 关闭文件描述符或数据库连接，释放资源。 |
| `sqlite3.connect` | 打开数据库连接；storage.connect 还负责迁移和提交/回滚，sqlite3.connect 是底层连接。 |
| `source.as_uri` | 把本地路径安全编码成 SQLite 只读 URI。 |
| `original.backup` | 调用 SQLite 在线快照接口，在正在运行的数据库上得到一致副本。 |
| `copied.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `copied.execute('PRAGMA user_version').fetchone` | 读取一行数据库结果。 |
| `copied.close` | 关闭文件描述符或数据库连接，释放资源。 |
| `temporary.open` | 打开文件，使用 with 确保关闭。 |
| `os.fsync` | 把快照内容同步到磁盘。 |
| `handle.fileno` | 读取打开文件的描述符，用于 fsync。 |
| `os.link` | 以不覆盖已有目标的方式原子发布同一文件系统内的快照。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `hashlib.sha256(destination.read_bytes()).hexdigest` | 把摘要转换为十六进制字符串。 |
| `hashlib.sha256` | 计算不可逆 SHA256 指纹，用于 CSRF 派生、限流键或快照校验。 |
| `destination.read_bytes` | 读取快照字节用于 SHA256 校验。 |
| `storage.now` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `original.close` | 关闭文件描述符或数据库连接，释放资源。 |
| `temporary.unlink` | 移除本次创建的临时快照文件。 |

### `manage_account()`

[查看源码](../scripts/db_admin.py#L87)

功能：由服务器管理员撤销邀请或重置密码；password_digest 派生新散列，事务内检查最后一个管理员，UPDATE 修改账号并 DELETE 撤销该账号全部登录。

| 调用 | 作用 |
|---|---|
| `str` | 将路径、编号或受控错误转换为文本。 |
| `Path(db_path).resolve` | 规范化路径；strict=True 确保源库已存在。 |
| `Path` | 构造本地路径。 |
| `len` | 检查数量或长度限制。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `auth.password_digest` | 调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute('SELECT role,active FROM users WHERE user_id=?', (user_id,)).fetchone` | 读取一行数据库结果。 |
| `db.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1").fetchone` | 读取一行数据库结果。 |

### `main()`

[查看源码](../scripts/db_admin.py#L119)

功能：管理命令入口；argparse 读路径，getpass 隐藏密码，create_user 初始化，manage_account 管理邀请，copy_database 执行快照操作。

| 调用 | 作用 |
|---|---|
| `argparse.ArgumentParser` | 建立管理或压测命令行入口。 |
| `parser.add_subparsers` | 定义 bootstrap/backup/restore 子命令。 |
| `commands.add_parser` | 添加一个子命令。 |
| `bootstrap.add_argument` | 定义命令行参数及默认值。 |
| `child.add_argument` | 定义命令行参数及默认值。 |
| `parser.parse_args` | 解析并校验命令行参数。 |
| `getpass.getpass` | 隐藏终端密码输入，避免密码进入命令历史。 |
| `parser.error` | 输出受控异常类别或 CLI 参数错误，不打印密码。 |
| `auth.create_user` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `print` | 输出不含用户业务正文或凭据的管理/统计结果。 |
| `manage_account` | 功能：由服务器管理员撤销邀请或重置密码；password_digest 派生新散列，事务内检查最后一个管理员，UPDATE 修改账号并 DELETE 撤销该账号全部登录。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `json.dumps` | 把报告编码为 JSON。 |
| `copy_database` | 功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。 |

## scripts/load_test.py

### `percentile()`

[查看源码](../scripts/load_test.py#L25)

功能：计算最近秩百分位；sorted 排序、ceil 定位，空样本返回 None。

| 调用 | 作用 |
|---|---|
| `sorted` | 排序耗时样本。 |
| `max` | 取得最大值或约束计数下限。 |
| `math.ceil` | 向上取整，定位最近秩百分位。 |
| `len` | 检查数量或长度限制。 |

### `exercise()`

[查看源码](../scripts/load_test.py#L34)

功能：一个并发用户通过真实 HTTP 建单/重复确认/查询；Client 保存 Cookie，post/get 调接口，逐步断言业务结果并记录耗时。

| 调用 | 作用 |
|---|---|
| `httpx.Client` | 创建真实 HTTP 客户端，保存 Cookie；trust_env=False 避免本机代理影响隔离压测。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `login.json` | 解析 HTTP JSON 响应。 |
| `range` | 按确定次数准备账号或执行循环。 |
| `time.perf_counter` | 用高精度时钟计算压测耗时。 |
| `response.raise_for_status` | 把非成功响应变成可统计的压测错误。 |
| `response.json` | 解码接口返回的 JSON 数据。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `uuid4` | 生成一次请求或客户端提交的随机编号。 |
| `proposal.raise_for_status` | 把非成功响应变成可统计的压测错误。 |
| `repeated.raise_for_status` | 把非成功响应变成可统计的压测错误。 |
| `repeated.json` | 解析 HTTP JSON 响应。 |
| `proposal.json` | 解析 HTTP JSON 响应。 |
| `first.raise_for_status` | 把非成功响应变成可统计的压测错误。 |
| `second.raise_for_status` | 把非成功响应变成可统计的压测错误。 |
| `first.json` | 解析 HTTP JSON 响应。 |
| `second.json` | 解析 HTTP JSON 响应。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `result.raise_for_status` | 把非成功响应变成可统计的压测错误。 |
| `result.json` | 解析 HTTP JSON 响应。 |
| `tickets.append` | 收集输出或测试统计。 |
| `errors.append` | 收集输出或测试统计。 |
| `type` | 读取异常类型名称，避免输出异常中的私人文本。 |
| `samples.append` | 收集输出或测试统计。 |

### `run_load()`

[查看源码](../scripts/load_test.py#L103)

功能：准备隔离数据库并启动 Uvicorn；线程池模拟用户，SQLite 核对唯一写入，copy_database 实际备份恢复，finally 关闭服务。

| 调用 | 作用 |
|---|---|
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `tempfile.TemporaryDirectory` | 为压测创建独立临时目录，退出后自动清理。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `Path` | 构造本地路径。 |
| `secrets.token_urlsafe` | 生成仅用于隔离测试的随机密码。 |
| `auth.create_user` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute("SELECT password_hash FROM users WHERE user_id='loadadmin'").fetchone` | 读取一行数据库结果。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `range` | 按确定次数准备账号或执行循环。 |
| `storage.now` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `socket.socket` | 建立本机临时端口探测套接字。 |
| `listener.bind` | 向系统申请空闲本机端口。 |
| `listener.getsockname` | 读取系统分配的端口。 |
| `open` | 打开文件，使用 with 确保关闭。 |
| `subprocess.Popen` | 启动独立 Uvicorn 子进程，使用隔离数据库和禁用模型的环境。 |
| `httpx.Client` | 创建真实 HTTP 客户端，保存 Cookie；trust_env=False 避免本机代理影响隔离压测。 |
| `process.poll` | 检查服务子进程是否已退出。 |
| `RuntimeError` | 报告服务无法启动等执行错误。 |
| `probe.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `time.sleep` | 短暂等待本机服务启动；有次数上限。 |
| `TimeoutError` | 报告有界启动等待超时。 |
| `time.perf_counter` | 用高精度时钟计算压测耗时。 |
| `concurrent.futures.ThreadPoolExecutor` | 并行模拟客户端或重复请求。 |
| `pool.submit` | 提交一个并发用户的工作。 |
| `future.result` | 等待任务并读取返回值；storage.result 是项目统一业务结果。 |
| `db.execute('SELECT count(*) FROM tickets').fetchone` | 读取一行数据库结果。 |
| `db.execute("SELECT count(*) FROM ticket_events WHERE action='create_ticket'").fetchone` | 读取一行数据库结果。 |
| `copy_database` | 功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。 |
| `sqlite3.connect` | 打开数据库连接；storage.connect 还负责迁移和提交/回滚，sqlite3.connect 是底层连接。 |
| `db.execute('SELECT count(*) FROM login_sessions').fetchone` | 读取一行数据库结果。 |
| `len` | 检查数量或长度限制。 |
| `set` | 计算去重集合或检查未知字段。 |
| `round` | 控制统计数值的小数位。 |
| `statistics.mean` | 计算流程延迟平均值。 |
| `percentile` | 功能：计算最近秩百分位；sorted 排序、ceil 定位，空样本返回 None。 |
| `process.terminate` | 向本脚本创建的服务发出退出信号。 |
| `process.wait` | 等待子进程退出，超时后再处理。 |
| `process.kill` | 只在自己的子进程无法正常退出时强制结束它。 |

### `main()`

[查看源码](../scripts/load_test.py#L229)

功能：解析压测规模并输出报告；run_load 完成隔离演练，write_text 写统计信息，失败以非零状态退出。

| 调用 | 作用 |
|---|---|
| `argparse.ArgumentParser` | 建立管理或压测命令行入口。 |
| `parser.add_argument` | 定义命令行参数及默认值。 |
| `parser.parse_args` | 解析并校验命令行参数。 |
| `run_load` | 功能：准备隔离数据库并启动 Uvicorn；线程池模拟用户，SQLite 核对唯一写入，copy_database 实际备份恢复，finally 关闭服务。 |
| `Path` | 构造本地路径。 |
| `output.parent.mkdir` | 创建目标目录。 |
| `output.write_text` | 保存人类可读的统计报告。 |
| `json.dumps` | 把报告编码为 JSON。 |
| `print` | 输出不含用户业务正文或凭据的管理/统计结果。 |
| `SystemExit` | 以明确退出码结束命令。 |

## src/react_agent/quotas.py

### `LimitReached.__init__()`

[查看源码](../src/react_agent/quotas.py#L17)

功能：保存限额结果；Exception 初始化说明，ceil/max 将等待秒数规范为正整数。

| 调用 | 作用 |
|---|---|
| `super().__init__` | 初始化异常基类并保存可公开的错误说明。 |
| `super` | 取得父类代理，复用标准 Exception 的初始化行为。 |
| `max` | 取得最大值或约束计数下限。 |
| `math.ceil` | 向上取整，定位最近秩百分位。 |

### `positive_integer()`

[查看源码](../src/react_agent/quotas.py#L24)

功能：读取正整数配置；getenv/int 转换参数，错误时拒绝启动，避免意外关闭限额。

| 调用 | 作用 |
|---|---|
| `int` | 解析计数或参数。 |
| `os.getenv` | 读取环境配置，默认值用于本机启动。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |

### `decimal_setting()`

[查看源码](../src/react_agent/quotas.py#L32)

功能：读取可选金额/单价；Decimal 与 is_finite 拒绝负数、NaN 和无穷，不使用浮点数记账。

| 调用 | 作用 |
|---|---|
| `os.getenv(name, '').strip` | 删除首尾空白，识别空消息或空配置。 |
| `os.getenv` | 读取环境配置，默认值用于本机启动。 |
| `Decimal` | 从文本或整数构造十进制定点数，用于预算及单价计算。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `value.is_finite` | 拒绝无穷或 NaN 配置值。 |

### `micro_amount()`

[查看源码](../src/react_agent/quotas.py#L46)

功能：把 Decimal 向上取整为微单位；to_integral_value 避免低估不足一微单位的费用。

| 调用 | 作用 |
|---|---|
| `int` | 解析计数或参数。 |
| `value.to_integral_value` | 按指定规则向上取整，避免低估不足一微单位的费用。 |

### `DemoLimits.from_env()`

[查看源码](../src/react_agent/quotas.py#L65)

功能：加载后端配额；positive_integer/decimal_setting 校验配置，金额上限必须配套两项模型单价。

| 调用 | 作用 |
|---|---|
| `decimal_setting` | 功能：读取可选金额/单价；Decimal 与 is_finite 拒绝负数、NaN 和无穷，不使用浮点数记账。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `os.getenv('DEMO_MODEL_ENABLED', 'true').lower` | 统一配置布尔值的大小写，再严格检查 true 或 false。 |
| `os.getenv` | 读取环境配置，默认值用于本机启动。 |
| `cls` | 调用 DemoLimits 数据类构造器，保存已经校验的应用配置。 |
| `positive_integer` | 功能：读取正整数配置；getenv/int 转换参数，错误时拒绝启动，避免意外关闭限额。 |
| `micro_amount` | 功能：把 Decimal 向上取整为微单位；to_integral_value 避免低估不足一微单位的费用。 |

### `DemoLimits.reserve_cost()`

[查看源码](../src/react_agent/quotas.py#L88)

功能：按较高单价预留本轮费用；max 选单价，micro_amount 向上取整，未知单价不伪造金额。

| 调用 | 作用 |
|---|---|
| `micro_amount` | 功能：把 Decimal 向上取整为微单位；to_integral_value 避免低估不足一微单位的费用。 |
| `Decimal` | 从文本或整数构造十进制定点数，用于预算及单价计算。 |
| `max` | 取得最大值或约束计数下限。 |

### `acquire()`

[查看源码](../src/react_agent/quotas.py#L95)

功能：事务内取得执行席位并预留日预算；connect/execute 串行检查请求、账号频率、并发、Token 和金额，uuid4 生成租约。

| 调用 | 作用 |
|---|---|
| `time.time` | 取得 Unix 时间，与登录窗口/租约到期时间比较。 |
| `datetime.fromtimestamp(current, UTC).date().isoformat` | 把到期时间转换为可保存的 ISO 时间文本。 |
| `datetime.fromtimestamp(current, UTC).date` | 取得 UTC 日历日期。 |
| `datetime.fromtimestamp` | 把 Unix 时间按 UTC 转为日期，用于自然日预算分组。 |
| `math.floor` | 向下取整以定位下一次 UTC 零点。 |
| `policy.reserve_cost` | 按输入/输出较高单价估算本次预留金额，向上取整为微币种单位。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute('SELECT status FROM requests WHERE request_id=? AND user_id=?', (request_id, user_id)).fetchone` | 读取一行数据库结果。 |
| `PermissionError` | 拒绝账号无权访问的请求，不消耗模型预算。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `LimitReached` | 创建携带错误码、用户说明和重试秒数的额度拒绝异常。 |
| `db.execute("SELECT user_id,expires_at FROM model_admissions WHERE state='active' AND expires_at>?", (current,)` | 取出所有有效席位，检查账号和全站并发。 |
| `len` | 检查数量或长度限制。 |
| `min` | 取得最早租约到期或最小等待值。 |
| `db.execute('SELECT count(*),min(started_at) FROM model_admissions WHERE user_id=? AND started_at>?', (user_id,` | 读取一行数据库结果。 |
| `db.execute('SELECT coalesce(sum(charged_tokens),0),coalesce(sum(charged_cost_micro),0),\n            coalesce(` | 读取一行数据库结果。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `uuid4` | 生成一次请求或客户端提交的随机编号。 |

### `settle()`

[查看源码](../src/react_agent/quotas.py#L184)

功能：释放席位并结算本次增量；未知或估算用量保留预留值，已知 usage 用差值避免重试重复计费；事务使重复结算无效。

| 调用 | 作用 |
|---|---|
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute("SELECT * FROM model_admissions WHERE admission_id=? AND state='active'", (identifier,)).fetchone` | 读取一行数据库结果。 |
| `max` | 取得最大值或约束计数下限。 |
| `current.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `previous.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `policy.reserve_cost` | 按输入/输出较高单价估算本次预留金额，向上取整为微币种单位。 |
| `micro_amount` | 功能：把 Decimal 向上取整为微单位；to_integral_value 避免低估不足一微单位的费用。 |
| `Decimal` | 从文本或整数构造十进制定点数，用于预算及单价计算。 |

### `overview()`

[查看源码](../src/react_agent/quotas.py#L228)

功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。

| 调用 | 作用 |
|---|---|
| `time.time` | 取得 Unix 时间，与登录窗口/租约到期时间比较。 |
| `datetime.fromtimestamp(current, UTC).date().isoformat` | 把到期时间转换为可保存的 ISO 时间文本。 |
| `datetime.fromtimestamp(current, UTC).date` | 取得 UTC 日历日期。 |
| `datetime.fromtimestamp` | 把 Unix 时间按 UTC 转为日期，用于自然日预算分组。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute('SELECT coalesce(sum(charged_tokens),0),coalesce(sum(charged_cost_micro),0),count(*) FROM model_adm` | 读取一行数据库结果。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute("SELECT count(*) FROM model_admissions WHERE state='active' AND expires_at>?", (current,)).fetchone` | 读取一行数据库结果。 |

## scripts/backup_worker.py

### `backup_once()`

[查看源码](../scripts/backup_worker.py#L14)

功能：保存一个新的完整快照；copy_database 在线一致备份并校验，replace 原子更新成功标记，uuid4 防止文件重名。

| 调用 | 作用 |
|---|---|
| `Path` | 构造本地路径。 |
| `directory.mkdir` | 创建目标目录。 |
| `datetime.now(UTC).strftime` | 生成 UTC 时间文件名，便于辨认快照。 |
| `datetime.now` | 取得带时区的当前时间。 |
| `copy_database` | 功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。 |
| `uuid4` | 生成一次请求或客户端提交的随机编号。 |
| `temporary.write_text` | 保存人类可读的统计报告。 |
| `json.dumps` | 把报告编码为 JSON。 |
| `os.chmod` | 将备份标记设为仅当前用户读写。 |
| `temporary.replace` | 原子替换成功标记；只有新快照完成才更新健康时间。 |
| `temporary.unlink` | 移除本次创建的临时快照文件。 |

### `healthy()`

[查看源码](../scripts/backup_worker.py#L33)

功能：检查最近备份是否仍在有效时间内；read_text/loads 读取标记，stat 检查快照和标记时间，不因进程存活就认定备份成功。

| 调用 | 作用 |
|---|---|
| `Path` | 构造本地路径。 |
| `json.loads` | 把 JSON 文本解码成字典或列表。 |
| `marker.read_text` | 读取 UTF-8 备份成功标记或测试文件。 |
| `Path(report['path']).is_file` | 确认成功标记指向的快照仍存在。 |
| `time.time` | 取得 Unix 时间，与登录窗口/租约到期时间比较。 |
| `marker.stat` | 读取文件权限，测试快照权限为 0600。 |

### `main()`

[查看源码](../scripts/backup_worker.py#L46)

功能：运行一次备份、周期备份或健康检查；argparse 校验参数，backup_once 执行，healthy 返回退出码，sleep 控制间隔。

| 调用 | 作用 |
|---|---|
| `argparse.ArgumentParser` | 建立管理或压测命令行入口。 |
| `parser.add_argument` | 定义命令行参数及默认值。 |
| `parser.parse_args` | 解析并校验命令行参数。 |
| `parser.error` | 输出受控异常类别或 CLI 参数错误，不打印密码。 |
| `SystemExit` | 以明确退出码结束命令。 |
| `healthy` | 功能：检查最近备份是否仍在有效时间内；read_text/loads 读取标记，stat 检查快照和标记时间，不因进程存活就认定备份成功。 |
| `print` | 输出不含用户业务正文或凭据的管理/统计结果。 |
| `json.dumps` | 把报告编码为 JSON。 |
| `backup_once` | 功能：保存一个新的完整快照；copy_database 在线一致备份并校验，replace 原子更新成功标记，uuid4 防止文件重名。 |
| `type` | 读取异常类型名称，避免输出异常中的私人文本。 |
| `time.sleep` | 短暂等待本机服务启动；有次数上限。 |

## tests/test_quotas.py

### `request_for()`

[查看源码](../tests/test_quotas.py#L17)

功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。

| 调用 | 作用 |
|---|---|
| `sessions.create_thread` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `sessions.begin_request` | 事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。 |

### `admit()`

[查看源码](../tests/test_quotas.py#L23)

功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。

| 调用 | 作用 |
|---|---|
| `quotas.acquire` | 功能：事务内取得执行席位并预留日预算；connect/execute 串行检查请求、账号频率、并发、Token 和金额，uuid4 生成租约。 |

### `test_concurrent_admission_is_atomic_and_checks_ownership()`

[查看源码](../tests/test_quotas.py#L28)

功能：ThreadPoolExecutor 同时争抢一个席位，只有一人通过；错误归属通过 raises 验证不会消耗额度。

| 调用 | 作用 |
|---|---|
| `quotas.DemoLimits` | 建立应用拥有的执行限额对象；测试传入较小限额来触发边界。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `ThreadPoolExecutor` | 并行模拟客户端或重复请求。 |
| `list` | 展开迭代结果。 |
| `pool.map` | 将输入分配给多个工作线程。 |
| `outcomes.count` | 统计列表中等于指定错误码的结果数量。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |
| `admit` | 功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |

### `test_concurrent_admission_is_atomic_and_checks_ownership.attempt()`

[查看源码](../tests/test_quotas.py#L33)

功能：模拟一个账号提交；admit 成功返回编号，LimitReached 转为错误码便于核对并发结果。

| 调用 | 作用 |
|---|---|
| `admit` | 功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。 |

### `test_daily_reservation_settlement_and_retry_delta()`

[查看源码](../tests/test_quotas.py#L49)

功能：检查先预留、仅按重试增量结算及重复结算无效；settle 之后读取 overview，并用新 policy 证明计数持久化。

| 调用 | 作用 |
|---|---|
| `quotas.DemoLimits` | 建立应用拥有的执行限额对象；测试传入较小限额来触发边界。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `admit` | 功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。 |
| `quotas.settle` | 功能：释放席位并结算本次增量；未知或估算用量保留预留值，已知 usage 用差值避免重试重复计费；事务使重复结算无效。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |

### `test_same_account_cannot_bypass_seat_limit_with_new_thread()`

[查看源码](../tests/test_quotas.py#L66)

功能：同账号开新会话仍只能运行一次；admit 在全站尚有席位时拒绝第二次，settle 后才允许继续。

| 调用 | 作用 |
|---|---|
| `quotas.DemoLimits` | 建立应用拥有的执行限额对象；测试传入较小限额来触发边界。 |
| `admit` | 功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |
| `quotas.settle` | 功能：释放席位并结算本次增量；未知或估算用量保留预留值，已知 usage 用差值避免重试重复计费；事务使重复结算无效。 |

### `test_crash_expires_seat_but_keeps_reservation_and_day_rolls_over()`

[查看源码](../tests/test_quotas.py#L78)

功能：模拟崩溃、租约过期及 UTC 跨日；monkeypatch 调时钟，旧预留不退回，次日额度按新日计算。

| 调用 | 作用 |
|---|---|
| `monkeypatch.setattr` | 测试期间替换模型加载入口，避免真实调用。 |
| `quotas.DemoLimits` | 建立应用拥有的执行限额对象；测试传入较小限额来触发边界。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `admit` | 功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |

### `test_estimated_unknown_and_money_budget()`

[查看源码](../tests/test_quotas.py#L96)

功能：估算/未知用量保留预算且按高单价预留；settle/overview 核对金额，再用 acquire 检查金额上限确实阻止执行。

| 调用 | 作用 |
|---|---|
| `quotas.DemoLimits` | 建立应用拥有的执行限额对象；测试传入较小限额来触发边界。 |
| `Decimal` | 从文本或整数构造十进制定点数，用于预算及单价计算。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `admit` | 功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。 |
| `quotas.settle` | 功能：释放席位并结算本次增量；未知或估算用量保留预留值，已知 usage 用差值避免重试重复计费；事务使重复结算无效。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |

### `test_exact_money_and_per_account_rate()`

[查看源码](../tests/test_quotas.py#L121)

功能：核对精确用量的输入/输出单价以及每账号频率；settle 按差值结算，admit 拒绝一分钟内超额重试。

| 调用 | 作用 |
|---|---|
| `quotas.DemoLimits` | 建立应用拥有的执行限额对象；测试传入较小限额来触发边界。 |
| `Decimal` | 从文本或整数构造十进制定点数，用于预算及单价计算。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `admit` | 功能：调用 acquire 模拟 HTTP 的预算预留；固定 160 秒租约，返回持久记录编号。 |
| `quotas.settle` | 功能：释放席位并结算本次增量；未知或估算用量保留预留值，已知 usage 用差值避免重试重复计费；事务使重复结算无效。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |

### `test_invalid_operator_configuration_is_rejected()`

[查看源码](../tests/test_quotas.py#L154)

功能：参数化错误配置在启动阶段被拒绝；delenv 清除本机单价，setenv 注入异常值，from_env 必须抛错。

| 调用 | 作用 |
|---|---|
| `monkeypatch.delenv` | 测试期间移除某个配置变量，退出测试后由 monkeypatch 恢复。 |
| `monkeypatch.setenv` | 测试期间替换环境配置，结束后恢复。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |
| `quotas.DemoLimits.from_env` | 功能：加载后端配额；positive_integer/decimal_setting 校验配置，金额上限必须配套两项模型单价。 |

### `test_http_agent_confirmation_refresh_and_budget_persist()`

[查看源码](../tests/test_quotas.py#L167)

功能：完整 HTTP 登录→模型工具→确认→重放→新应用恢复；脚本模型替代远程模型，真实 LangGraph/SQLite 和额度拦截全部执行。

| 调用 | 作用 |
|---|---|
| `monkeypatch.setenv` | 测试期间替换环境配置，结束后恢复。 |
| `tool_call` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `ScriptedModel` | 按预设顺序返回消息或抛出异常，测试无需访问真实模型。 |
| `AIMessage` | 构造模拟模型回复或工具调用的 LangChain 消息。 |
| `monkeypatch.setattr` | 测试期间替换模型加载入口，避免真实调用。 |
| `importlib.import_module` | 导入需要替换模型的模块。 |
| `TestClient` | 在测试中运行 ASGI 应用及生命周期，同时走完整 HTTP 参数与认证层。 |
| `create_app` | 功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。 |
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `new_thread` | 功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。 |
| `client.post(f'/api/threads/{thread}/requests', headers={'Idempotency-Key': 'full-agent-001'}, json={'text': 'X` | 解析 HTTP JSON 响应。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `first.json` | 解析 HTTP JSON 响应。 |
| `storage.list_tickets` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `client.get(f'/api/threads/{thread}').json` | 解析 HTTP JSON 响应。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `client.post(endpoint, json={'thread_id': thread}).json` | 解析 HTTP JSON 响应。 |
| `client.post(f'/api/requests/{rid}/run').json` | 解析 HTTP JSON 响应。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |
| `dict` | 复制客户端 Cookie 映射，模拟浏览器在服务重启后仍保留原登录。 |
| `fresh.get('/api/session').json` | 解析 HTTP JSON 响应。 |
| `fresh.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `fresh.get(f'/api/threads/{thread}').json` | 解析 HTTP JSON 响应。 |
| `fresh.get(f'/api/tickets/{ticket_id}', params={'thread_id': thread}).json` | 解析 HTTP JSON 响应。 |
| `len` | 检查数量或长度限制。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `fresh.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `denied.json` | 解析 HTTP JSON 响应。 |
| `int` | 解析计数或参数。 |
| `sessions.get_request` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |

### `test_http_pause_does_not_block_completed_results_or_forms()`

[查看源码](../tests/test_quotas.py#L253)

功能：关闭模型仍能使用工单表单和读取已完成结果；post 检查 429，overview 验证拒绝未占用预算。

| 调用 | 作用 |
|---|---|
| `monkeypatch.setenv` | 测试期间替换环境配置，结束后恢复。 |
| `TestClient` | 在测试中运行 ASGI 应用及生命周期，同时走完整 HTTP 参数与认证层。 |
| `create_app` | 功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。 |
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `client.post(f'/api/requests/{rid}/run').json` | 解析 HTTP JSON 响应。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `propose` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |
| `new_thread` | 功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。 |
| `client.post(f'/api/requests/{response.json()['request_id']}/run').json` | 解析 HTTP JSON 响应。 |
| `response.json` | 解码接口返回的 JSON 数据。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |

### `test_http_unexpected_failure_releases_seat_conservatively()`

[查看源码](../tests/test_quotas.py#L281)

功能：模拟业务入口异常；run 的 finally 仍执行 settle 释放席位，overview 证明预算没有被误退款。

| 调用 | 作用 |
|---|---|
| `monkeypatch.setattr` | 测试期间替换模型加载入口，避免真实调用。 |
| `monkeypatch.setenv` | 测试期间替换环境配置，结束后恢复。 |
| `TestClient` | 在测试中运行 ASGI 应用及生命周期，同时走完整 HTTP 参数与认证层。 |
| `create_app` | 功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。 |
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `request_for` | 功能：为指定测试账号建立独立待执行请求；create_thread/begin_request 持久保存会话和消息，避免干扰其他用例。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |

### `test_http_unexpected_failure_releases_seat_conservatively.crash()`

[查看源码](../tests/test_quotas.py#L285)

功能：抛出确定性异常，制造无法取得用量的失败；不调用远程模型。

| 调用 | 作用 |
|---|---|
| `RuntimeError` | 报告服务无法启动等执行错误。 |

## tests/test_demo_ops.py

### `test_backup_worker_checks_snapshot_age_and_failure()`

[查看源码](../tests/test_demo_ops.py#L15)

功能：验证成功后发布标记、过期后不健康、失败不冒充成功；backup_once/healthy 执行真实快照，utime 模拟旧备份。

| 调用 | 作用 |
|---|---|
| `healthy` | 功能：检查最近备份是否仍在有效时间内；read_text/loads 读取标记，stat 检查快照和标记时间，不因进程存活就认定备份成功。 |
| `backup_once` | 功能：保存一个新的完整快照；copy_database 在线一致备份并校验，replace 原子更新成功标记，uuid4 防止文件重名。 |
| `marker.read_bytes` | 读取快照字节用于 SHA256 校验。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |
| `os.utime` | 仅在测试中改变文件时间，模拟备份过期。 |
| `time.time` | 取得 Unix 时间，与登录窗口/租约到期时间比较。 |

### `test_backup_worker_command_runs_from_project()`

[查看源码](../tests/test_demo_ops.py#L30)

功能：子进程执行与容器相同的模块入口，避免导入路径只在 pytest 有效；subprocess.run 验证一次备份和健康检查退出码。

| 调用 | 作用 |
|---|---|
| `str` | 将路径、编号或受控错误转换为文本。 |
| `subprocess.run` | 启动独立 Python 子进程并等待，用退出码检查真实命令入口和模块导入路径。 |

### `test_restore_releases_model_seats_and_retains_budget()`

[查看源码](../tests/test_demo_ops.py#L48)

功能：恢复时释放旧进程的席位并保留未知用量；copy_database 生成新库，overview 检查计数，原库席位保持不变。

| 调用 | 作用 |
|---|---|
| `sessions.begin_request` | 事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。 |
| `sessions.create_thread` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `quotas.DemoLimits` | 建立应用拥有的执行限额对象；测试传入较小限额来触发边界。 |
| `quotas.acquire` | 功能：事务内取得执行席位并预留日预算；connect/execute 串行检查请求、账号频率、并发、Token 和金额，uuid4 生成租约。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `copy_database` | 功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。 |
| `quotas.overview` | 功能：给管理员提供当天汇总；SELECT 聚合预留及已结算用量，不包含账号、消息或模型凭据。 |

### `test_schema_three_upgrade_preserves_existing_records()`

[查看源码](../tests/test_demo_ops.py#L62)

功能：模拟 v3 库升级；execute 移除 v4 新表并标记旧版本，connect 重建新表，断言原会话和账号仍存在。

| 调用 | 作用 |
|---|---|
| `sessions.create_thread` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute('PRAGMA user_version').fetchone` | 读取一行数据库结果。 |
| `db.execute('SELECT count(*) FROM model_admissions').fetchone` | 读取一行数据库结果。 |
| `sessions.get_thread` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `auth.get_user` | 调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。 |

### `test_password_reset_and_invitation_revocation()`

[查看源码](../tests/test_demo_ops.py#L75)

功能：重置密码立即撤销旧登录，停用账号阻止登录和取身份；manage_account 修改真实库，authenticate/login 核验边界。

| 调用 | 作用 |
|---|---|
| `auth.login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `manage_account` | 功能：由服务器管理员撤销邀请或重置密码；password_digest 派生新散列，事务内检查最后一个管理员，UPDATE 修改账号并 DELETE 撤销该账号全部登录。 |
| `auth.authenticate` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |
| `auth.get_user` | 调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |

## tests/test_api.py

### `client()`

[查看源码](../tests/test_api.py#L17)

功能：TestClient 启动完整 API 生命周期；create_app 指向测试库，Origin 与服务地址一致。

| 调用 | 作用 |
|---|---|
| `TestClient` | 在测试中运行 ASGI 应用及生命周期，同时走完整 HTTP 参数与认证层。 |
| `create_app` | 功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。 |

### `login()`

[查看源码](../tests/test_api.py#L26)

功能：模拟网页登录；post 换取 Cookie，保存 CSRF 证明到后续请求头，并断言登录成功。

| 调用 | 作用 |
|---|---|
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `response.json` | 解码接口返回的 JSON 数据。 |

### `new_thread()`

[查看源码](../tests/test_api.py#L36)

功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。

| 调用 | 作用 |
|---|---|
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `response.json` | 解码接口返回的 JSON 数据。 |

### `propose()`

[查看源码](../tests/test_api.py#L43)

功能：发送有幂等键的手工建单提案；post 仅生成确认卡片，不直接写工单。

| 调用 | 作用 |
|---|---|
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |

### `test_cookie_refresh_csrf_and_logout()`

[查看源码](../tests/test_api.py#L55)

功能：验证凭据不进 URL/JSON，跨客户端刷新可恢复，CSRF 与 Origin 拦截修改，logout 撤销令牌；调用 login、TestClient、get/post。

| 调用 | 作用 |
|---|---|
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `client.cookies.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `TestClient` | 在测试中运行 ASGI 应用及生命周期，同时走完整 HTTP 参数与认证层。 |
| `fresh.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `fresh.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `session.json` | 解析 HTTP JSON 响应。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `auth.authenticate` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |

### `test_secure_cookie_and_origin_configuration()`

[查看源码](../tests/test_api.py#L81)

功能：验证 HTTPS Cookie 与非本机配置限制；create_app 拒绝明文公网配置，TestClient 检查真实 Set-Cookie 头。

| 调用 | 作用 |
|---|---|
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |
| `create_app` | 功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。 |
| `TestClient` | 在测试中运行 ASGI 应用及生命周期，同时走完整 HTTP 参数与认证层。 |
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |

### `test_login_rotation_url_rejected_and_password_not_echoed()`

[查看源码](../tests/test_api.py#L95)

功能：登录轮换旧令牌、拒绝 URL 登录及多余角色；auth.authenticate 验证旧会话撤销，响应不得包含密码。

| 调用 | 作用 |
|---|---|
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `client.cookies.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `auth.authenticate` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |
| `client.cookies.clear` | 清除退出登录后的 URL 参数或客户端 Cookie。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |

### `test_request_submission_replays_or_conflicts()`

[查看源码](../tests/test_api.py#L118)

功能：检查同键同内容仅保存一条消息，同键异内容冲突；post 重放后 get_thread 检查 transcript。

| 调用 | 作用 |
|---|---|
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `new_thread` | 功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `first.json` | 解析 HTTP JSON 响应。 |
| `second.json` | 解析 HTTP JSON 响应。 |
| `len` | 检查数量或长度限制。 |
| `sessions.get_thread` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |

### `test_concurrent_submission_has_one_request()`

[查看源码](../tests/test_api.py#L136)

功能：验证数据库事务承受同键并发提交；线程池调用 begin_request，检查所有请求编号一致及消息仅一份。

| 调用 | 作用 |
|---|---|
| `ThreadPoolExecutor` | 并行模拟客户端或重复请求。 |
| `list` | 展开迭代结果。 |
| `pool.map` | 将输入分配给多个工作线程。 |
| `range` | 按确定次数准备账号或执行循环。 |
| `len` | 检查数量或长度限制。 |
| `set` | 计算去重集合或检查未知字段。 |
| `sessions.get_thread` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |

### `test_concurrent_submission_has_one_request.submit()`

[查看源码](../tests/test_api.py#L139)

功能：模拟重复客户端；调用 begin_request 传入相同提交键和内容。

| 调用 | 作用 |
|---|---|
| `sessions.begin_request` | 事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。 |

### `test_http_confirmation_is_required_and_idempotent()`

[查看源码](../tests/test_api.py#L158)

功能：从 HTTP 提案到确认验证真实库；重复提交/确认均复用结果，SELECT 验证一张工单和一条创建审计。

| 调用 | 作用 |
|---|---|
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `new_thread` | 功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。 |
| `propose` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |
| `first.json` | 解析 HTTP JSON 响应。 |
| `repeated.json` | 解析 HTTP JSON 响应。 |
| `storage.list_tickets` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `client.get(f'/api/threads/{thread}').json` | 解析 HTTP JSON 响应。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `created.json` | 解析 HTTP JSON 响应。 |
| `again.json` | 解析 HTTP JSON 响应。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute('SELECT count(*) FROM tickets').fetchone` | 读取一行数据库结果。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute('SELECT count(*) FROM ticket_events').fetchone` | 读取一行数据库结果。 |

### `test_cross_user_forged_identity_and_permission_change()`

[查看源码](../tests/test_api.py#L180)

功能：验证越权会话/确认/管理员访问被拒绝；Cookie 切换用户，SQL 改真实角色后接口立即收回权限。

| 调用 | 作用 |
|---|---|
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `new_thread` | 功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。 |
| `propose(client, thread).json` | 解析 HTTP JSON 响应。 |
| `propose` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `storage.list_tickets` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

### `test_staff_creation_and_proposal_field_whitelist()`

[查看源码](../tests/test_api.py#L216)

功能：管理员创建人员可用，业务载荷无法伪造操作者或版本；调用 login、new_thread、post 检查 HTTP 边界。

| 调用 | 作用 |
|---|---|
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `new_thread` | 功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。 |

### `test_http_checkpoint_retry_uses_original_request()`

[查看源码](../tests/test_api.py#L246)

功能：通过 API 故意中断真实 LangGraph 再重试；ScriptedModel 替换远程模型，数据库检查只有一张卡片且预算累计。

| 调用 | 作用 |
|---|---|
| `monkeypatch.setenv` | 测试期间替换环境配置，结束后恢复。 |
| `ScriptedModel` | 按预设顺序返回消息或抛出异常，测试无需访问真实模型。 |
| `tool_call` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `RuntimeError` | 报告服务无法启动等执行错误。 |
| `AIMessage` | 构造模拟模型回复或工具调用的 LangChain 消息。 |
| `monkeypatch.setattr` | 测试期间替换模型加载入口，避免真实调用。 |
| `importlib.import_module` | 导入需要替换模型的模块。 |
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `new_thread` | 功能：通过 HTTP 新建本人会话；post/json 提取服务器生成的编号。 |
| `client.post(f'/api/threads/{thread}/requests', headers={'Idempotency-Key': 'model-retry-001'}, json={'text': '` | 解析 HTTP JSON 响应。 |
| `client.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `first.json` | 解析 HTTP JSON 响应。 |
| `resumed.json` | 解析 HTTP JSON 响应。 |
| `client.post(f'/api/requests/{rid}/run').json` | 解析 HTTP JSON 响应。 |
| `client.get(f'/api/threads/{thread}').json` | 解析 HTTP JSON 响应。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `len` | 检查数量或长度限制。 |
| `storage.list_tickets` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

### `test_login_rate_limit_persists_between_app_instances()`

[查看源码](../tests/test_api.py#L280)

功能：验证限流存数据库且时间窗口能恢复；consume_login_budget 预先占满，换应用后 login 仍返回 429，更新时间后恢复。

| 调用 | 作用 |
|---|---|
| `range` | 按确定次数准备账号或执行循环。 |
| `auth.consume_login_budget` | 功能：限制账号每分钟 10 次、来源每分钟 30 次登录尝试；调用 SHA256 隐藏键、time.time 计时、connect/execute 原子计数并清理旧窗口。 |
| `TestClient` | 在测试中运行 ASGI 应用及生命周期，同时走完整 HTTP 参数与认证层。 |
| `create_app` | 功能：构造 HTTP 应用；load_dotenv 加载配置，DemoLimits.from_env 校验限额，注册路由/依赖/异常处理，StaticFiles 提供同源页面。 |
| `other.post` | 在应用上注册 POST 路由；在测试客户端中发出带 Cookie/CSRF 的 POST 请求。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |

### `test_static_page_and_health_do_not_expose_secrets()`

[查看源码](../tests/test_api.py#L299)

功能：确认页面与健康检查可用，未登录不能读业务；get 检查 CSP、页面资源和身份边界。

| 调用 | 作用 |
|---|---|
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |

### `test_unexpected_error_does_not_expose_payload()`

[查看源码](../tests/test_api.py#L310)

功能：模拟内部异常，确认响应和日志不泄露正文；setattr 替换会话读取，caplog 检查日志仍有跟踪编号。

| 调用 | 作用 |
|---|---|
| `login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `monkeypatch.setattr` | 测试期间替换模型加载入口，避免真实调用。 |
| `caplog.at_level` | 在指定范围捕获目标日志级别，检查脱敏结果。 |
| `client.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `response.json` | 解码接口返回的 JSON 数据。 |

### `test_unexpected_error_does_not_expose_payload.broken()`

[查看源码](../tests/test_api.py#L314)

功能：抛出含模拟私人文本的 RuntimeError，验证 HTTP 统一异常边界。

| 调用 | 作用 |
|---|---|
| `RuntimeError` | 报告服务无法启动等执行错误。 |

## tests/test_backup.py

### `test_snapshot_restores_checkpoints_and_revokes_sessions()`

[查看源码](../tests/test_backup.py#L18)

功能：备份中断后的图状态并恢复到新库；copy_database 撤销登录/释放租约，run_request 真正续跑，验证原库保持失败状态。

| 调用 | 作用 |
|---|---|
| `auth.login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `ScriptedModel` | 按预设顺序返回消息或抛出异常，测试无需访问真实模型。 |
| `tool_call` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `RuntimeError` | 报告服务无法启动等执行错误。 |
| `importlib.import_module` | 导入需要替换模型的模块。 |
| `monkeypatch.setattr` | 测试期间替换模型加载入口，避免真实调用。 |
| `new_request` | 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。 |
| `asyncio.run` | 运行异步服务或 Streamlit 页面测试。 |
| `run_request` | claim_request 获取租约，用 aget_state 判断是否恢复检查点，astream 收集输出，finish_request 保存结果。 |
| `sessions.claim_request` | BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。 |
| `copy_database` | 功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。 |
| `os.stat` | 读取文件权限，测试快照权限为 0600。 |
| `auth.authenticate` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `sessions.get_request` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |
| `AIMessage` | 构造模拟模型回复或工具调用的 LangChain 消息。 |
| `Context` | 构造服务端运行上下文，包含真实用户、会话、请求和数据库位置。 |
| `actions.pending_actions` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `actions.confirm_action` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `len` | 检查数量或长度限制。 |
| `storage.list_tickets` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

### `test_snapshot_refuses_overwrite_and_invalid_source()`

[查看源码](../tests/test_backup.py#L60)

功能：防止误覆盖或把损坏文件当快照；copy_database 必须抛错且原目标字节不变。

| 调用 | 作用 |
|---|---|
| `target.write_bytes` | 写入测试字节，用于验证已有目标不会被覆盖。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |
| `copy_database` | 功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。 |
| `target.read_bytes` | 读取快照字节用于 SHA256 校验。 |
| `(tmp_path / 'new.db').exists` | 检查目标是否已存在，防止覆盖。 |

## src/react_agent/auth.py

### `consume_login_budget()`

[查看源码](../src/react_agent/auth.py#L171)

功能：限制账号每分钟 10 次、来源每分钟 30 次登录尝试；调用 SHA256 隐藏键、time.time 计时、connect/execute 原子计数并清理旧窗口。

| 调用 | 作用 |
|---|---|
| `time.time` | 取得 Unix 时间，与登录窗口/租约到期时间比较。 |
| `buckets.append` | 收集输出或测试统计。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `hashlib.sha256(key.encode()).hexdigest` | 把摘要转换为十六进制字符串。 |
| `hashlib.sha256` | 计算不可逆 SHA256 指纹，用于 CSRF 派生、限流键或快照校验。 |
| `key.encode` | 将字符串按默认 UTF-8 编码成字节。 |
| `db.execute('SELECT * FROM auth_limits WHERE bucket=?', (hashed,)).fetchone` | 读取一行数据库结果。 |

### `login()`

[查看源码](../src/react_agent/auth.py#L198)

先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。

| 调用 | 作用 |
|---|---|
| `isinstance` | 校验输入的实际类型。 |
| `len` | 检查数量或长度限制。 |
| `storage.result` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `consume_login_budget` | 功能：限制账号每分钟 10 次、来源每分钟 30 次登录尝试；调用 SHA256 隐藏键、time.time 计时、connect/execute 原子计数并清理旧窗口。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute('SELECT * FROM users WHERE user_id=? AND active=1', (user_id,)).fetchone` | 读取一行数据库结果。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `password_digest` | 调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。 |
| `hmac.compare_digest` | 以恒定时间方式比较令牌证明，避免普通比较的时序差异。 |
| `digest.split` | 按分隔符拆分密码摘要字段。 |
| `secrets.token_urlsafe` | 生成仅用于隔离测试的随机密码。 |
| `(datetime.now(UTC) + timedelta(hours=12)).isoformat` | 把到期时间转换为可保存的 ISO 时间文本。 |
| `datetime.now` | 取得带时区的当前时间。 |
| `timedelta` | 表示一段时长，用于计算登录到期时间。 |
| `hashlib.sha256(token.encode()).hexdigest` | 把摘要转换为十六进制字符串。 |
| `hashlib.sha256` | 计算不可逆 SHA256 指纹，用于 CSRF 派生、限流键或快照校验。 |
| `token.encode` | 将字符串按默认 UTF-8 编码成字节。 |
| `public_user` | 只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。 |

## src/react_agent/sessions.py

### `begin_request()`

[查看源码](../src/react_agent/sessions.py#L189)

事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。

| 调用 | 作用 |
|---|---|
| `isinstance` | 校验输入的实际类型。 |
| `text.strip` | 删除首尾空白，识别空消息或空配置。 |
| `len` | 检查数量或长度限制。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `re.fullmatch` | 检查整个字符串是否符合账号或幂等键格式。 |
| `get_thread` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `uuid4` | 生成一次请求或客户端提交的随机编号。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute('SELECT request_id,thread_id,input FROM requests WHERE user_id=? AND client_key=?', (user_id, clien` | 读取一行数据库结果。 |
| `db.execute('SELECT * FROM threads WHERE thread_id=? AND user_id=?', (thread_id, user_id)).fetchone` | 读取一行数据库结果。 |
| `db.execute("SELECT request_id FROM requests WHERE thread_id=? AND status IN ('pending','running','failed')", (` | 读取一行数据库结果。 |
| `extract_facts` | 调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。 |
| `json.loads` | 把 JSON 文本解码成字典或列表。 |
| `transcript.append` | 收集输出或测试统计。 |
| `storage.now` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `storage.encode` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |

## src/react_agent/storage.py

### `migrate()`

[查看源码](../src/react_agent/storage.py#L76)

在写事务中建表、按 PRAGMA table_info 增列；不删除或重新编号原工单。

| 调用 | 作用 |
|---|---|
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `additions.items` | 遍历字段与值。 |
| `db.commit` | 提交数据库事务。 |

### `connect()`

[查看源码](../src/react_agent/storage.py#L173)

调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。

| 调用 | 作用 |
|---|---|
| `database_path` | 调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。 |
| `target.parent.mkdir` | 创建目标目录。 |
| `sqlite3.connect` | 打开数据库连接；storage.connect 还负责迁移和提交/回滚，sqlite3.connect 是底层连接。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `db.execute('PRAGMA user_version').fetchone` | 读取一行数据库结果。 |
| `migrate` | 在写事务中建表、按 PRAGMA table_info 增列；不删除或重新编号原工单。 |
| `db.close` | 关闭文件描述符或数据库连接，释放资源。 |

## app.py

### `show_login()`

[查看源码](../app.py#L51)

显示首次管理员设置或登录/客户注册；调用 auth，角色不由聊天内容或 URL 指定。

| 调用 | 作用 |
|---|---|
| `st.title` | 显示页面主标题。 |
| `st.caption` | 显示辅助说明。 |
| `auth.users` | 供可信工作台列举人员；调用 connect/public_user 去除认证资料。 |
| `st.radio` | 显示单选项，用于选择首次初始化或登录。 |
| `st.info` | 输出不含正文或凭据的结构化 HTTP 统计。 |
| `st.form` | 将多个输入控件组合成一次提交的表单。 |
| `st.text_input` | 读取账号、密码等文本输入，密码模式隐藏字符。 |
| `st.form_submit_button` | 提交表单并返回本轮是否点击。 |
| `auth.create_user` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `st.error` | 输出受控异常类别或 CLI 参数错误，不打印密码。 |
| `auth.login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `st.rerun` | 从头重跑页面，在登录状态变化后刷新视图。 |

### `main()`

[查看源码](../app.py#L722)

恢复登录及选中会话，调用三个工作区；刷新不会清空 SQLite 中的对话和待确认卡片。

| 调用 | 作用 |
|---|---|
| `st.session_state.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `auth.authenticate` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |
| `show_login` | 显示首次管理员设置或登录/客户注册；调用 auth，角色不由聊天内容或 URL 指定。 |
| `sessions.list_threads` | 参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。 |
| `sessions.create_thread` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `st.query_params.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `st.subheader` | 显示分区标题。 |
| `st.write` | 显示文本或结构化对象。 |
| `st.selectbox` | 显示会话选择框并返回选中值。 |
| `ids.index` | 找到当前会话编号在选项中的位置。 |
| `st.button` | 显示按钮并返回本轮是否点击。 |
| `st.rerun` | 从头重跑页面，在登录状态变化后刷新视图。 |
| `st.caption` | 显示辅助说明。 |
| `Context` | 构造服务端运行上下文，包含真实用户、会话、请求和数据库位置。 |
| `model.startswith` | 判断地址或模型名是否具有指定前缀。 |
| `bool` | 转换为明确布尔值。 |
| `os.getenv(key, '').strip` | 删除首尾空白，识别空消息或空配置。 |
| `os.getenv` | 读取环境配置，默认值用于本机启动。 |
| `st.success` | 显示操作成功提示。 |
| `st.info` | 输出不含正文或凭据的结构化 HTTP 统计。 |
| `auth.logout` | 调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。 |
| `st.session_state.pop` | 移除会话状态中的旧值。 |
| `st.query_params.clear` | 清除退出登录后的 URL 参数或客户端 Cookie。 |
| `app_context` | 创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。 |
| `st.title` | 显示页面主标题。 |
| `st.empty` | 创建可被后续内容替换的页面占位。 |
| `notice_box.info` | 输出不含正文或凭据的结构化 HTTP 统计。 |
| `st.tabs` | 建立对话和工单工作台等页签。 |
| `show_chat` | 调用 begin_request/run_request 执行对话；页面刷新后从 SQLite 恢复记录、待确认和失败重试。 |
| `show_workbench` | 按权限筛选工单，提供详情、状态统计和可手工填写的建单表单，不依赖模型连通性。 |
| `len` | 检查数量或长度限制。 |
| `show_admin` | 管理员创建真实工作人员与专长规则；调用 create_user 再次检查管理权限。 |

## tests/test_app.py

### `test_old_url_session_is_not_accepted()`

[查看源码](../tests/test_app.py#L70)

功能：防止旧 URL 登录方式复活；auth.login 取有效测试令牌，AppTest 只通过查询参数传入，仍应显示登录页并清除参数。

| 调用 | 作用 |
|---|---|
| `monkeypatch.setenv` | 测试期间替换环境配置，结束后恢复。 |
| `auth.login` | 先调用 consume_login_budget 限流，再用 password_digest/compare_digest 校验；生成 12 小时会话，数据库仅存令牌散列。 |
| `AppTest.from_file` | 从 app.py 创建 Streamlit 测试实例。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `app.run` | 运行异步服务或 Streamlit 页面测试。 |

## 网页 JavaScript 函数

浏览器通过 fetch 调用 API；Cookie 由浏览器自动携带，页面只持有 CSRF 证明。用户输入使用 textContent 显示，不执行 HTML。

| 函数 | 功能与调用 |
|---|---|
| `byId` | 取页面节点；内部调用 getElementById，避免重复选择表达式。 |
| `element` | 安全创建显示节点；textContent 让用户文字只作为文本，不执行 HTML。 |
| `notice` | 展示结果或错误；通过 textContent/hidden 更新提示，不输出请求凭据。 |
| `api` | 统一访问同源 API；fetch 携带 Cookie 与 CSRF，json 解析结果，非成功状态抛出受控错误。 |
| `busy` | 防止连续点击并统一报错；回调执行后在 finally 中恢复按钮，失败时保留原提交编号。 |
| `submitOnce` | 浏览器重试沿用提交编号；SHA256 只保存正文指纹，sessionStorage 不保存密码、会话令牌或消息正文。 |
| `enter` | 进入已认证页面；api 读取会话列表，必要时创建会话，refresh 恢复业务状态。 |
| `refresh` | 刷新当前会话、确认卡片及工单；replaceChildren 清空旧显示，内容始终来自已授权 API。 |
| `renderConfirmations` | 把冻结参数显示为人工可读的卡片；确认按钮只向服务器发送 operation_id 和用户选择。 |
| `loadTickets` | 查询并绘制权限范围内工单；api 使用筛选参数，详情按钮调用 showTicket。 |
| `showTicket` | 显示真实工单与处理历史；textContent 防止故障描述中的 HTML 被执行。 |
| `configureActions` | 只呈现当前角色和状态适用的操作；filter 筛选状态、element 构造选项，服务器仍会再次检查权限。 |
| `runRequest` | 继续原请求；run 接口复用服务层检查点，finally 刷新数据库中的实际状态。 |
| `bindEvents` | 安装表单与按钮事件；FormData 取输入，submitOnce 负责提交幂等，业务写入仍需卡片确认。 |
| `start` | 初始化页面；先绑定事件，再尝试通过 Cookie 恢复会话，未登录时保留登录表单。 |
