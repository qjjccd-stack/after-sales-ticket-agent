# 逐个函数的功能与内部调用说明

本页覆盖 v2 的 **169 个具名函数/方法/内部函数**：应用与评测脚本 99 个，测试及夹具 70 个。相同的中文讲解已写在每个函数定义上方，可直接在 VS Code 阅读。v3 新增及修改函数另见 [HTTP 与运维函数讲解](http-functions.md)，实际位置以当前源码中的函数定义为准。

2026-10-10 评测契约已升级。`scripts/evaluate.py` 和评测器测试的最新功能、内部调用，以及新增 `evaluation.py` 的讲解，以 [评测函数说明](evaluation-functions.md) 为准；任务标准与失败案例见 [评测指南](evaluation.md)。本页保留旧版本学习记录。

每项先解释当前函数的作用，再解释它用到的项目函数、第三方接口和基础方法。链式调用按内层到外层展开；传给线程、状态图和组件的回调单独标出。表内 `(...)` 省略实参，“字符串/字典字面量”表示直接写在代码里的对象。

阅读顺序：`app.main → service.run_request → graph.build_graph → graph.call_model / execute_tools → tools → actions → storage`。会话和故障记忆看 `sessions.py`，检索看 `knowledge.py`，账号看 `auth.py`。

2026-10-08 的讲解改动只增加 `#` 注释并更新文档，当时通过 AST 核对。2026-10-09 的 v3 则实际增加了 HTTP 与运维逻辑，不能用那次“仅注释”核对证明 v3 与 v2 完全相同；新版本验收见 acceptance-v3.md。

## 文件索引

- `app.py`：10 个函数。
- `src/react_agent/actions.py`：13 个函数。
- `src/react_agent/auth.py`：8 个函数。
- `src/react_agent/graph.py`：9 个函数。
- `src/react_agent/knowledge.py`：5 个函数。
- `src/react_agent/service.py`：3 个函数。
- `src/react_agent/sessions.py`：12 个函数。
- `src/react_agent/storage.py`：14 个函数。
- `src/react_agent/tools.py`：11 个函数。
- `src/react_agent/utils.py`：3 个函数。
- `scripts/evaluate.py`：10 个函数。
- `scripts/smoke_model.py`：1 个函数。
- `tests/conftest.py`：4 个函数。
- `tests/test_actions.py`：19 个函数。
- `tests/test_app.py`：6 个函数。
- `tests/test_context.py`：10 个函数。
- `tests/test_evaluation.py`：5 个函数。
- `tests/test_graph.py`：15 个函数。
- `tests/test_tickets.py`：11 个函数。

## 一次请求的调用链

```text
app.show_chat
  ├─ sessions.begin_request：保存用户输入、生成请求编号
  └─ service.run_request：取得执行租约、恢复检查点
      └─ graph.build_graph 编排的节点
          ├─ prepare：恢复事实和裁剪历史
          ├─ call_model：模型根据上下文提出工具请求
          ├─ execute_tools：校验并执行 TOOLS 中的函数
          │   ├─ search_faq → knowledge.search：只读检索
          │   └─ 写工具 → actions.propose：只生成确认卡片
          └─ finalize：按真实工具结果生成可见回复

app.show_confirmations
  └─ actions.confirm_action：页面点击后才允许进入
      ├─ 再查身份、权限、冻结参数、有效期和版本
      ├─ SQLite 事务更新工单并写审计
      └─ actions.render_result：返回实际提交的状态
```

## app.py

### 1. `show_login()`

[查看函数源码](../app.py#L51)

**当前函数的功能：** 显示首次管理员设置或登录/客户注册；调用 auth，角色不由聊天内容或 URL 指定。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `st.title()` | 显示页面一级标题。 |
| `st.caption()` | 显示辅助说明，例如 UTC 时间、模型配置或统计口径。 |
| `auth.users()` | 供可信工作台列举人员；调用 connect/public_user 去除认证资料。 |
| `st.radio()` | 显示单选项，用于切换登录与客户注册。 |
| `st.info()` | 显示普通提示，例如等待确认、无密钥或操作结果。 |
| `st.form()` | 创建表单容器，将一组输入汇集到一次提交。 |
| `st.text_input()` | 显示单行文本框并返回输入；type=password 时隐藏密码。 |
| `st.form_submit_button()` | 绘制表单提交按钮，返回本轮是否发生提交。 |
| `auth.create_user()` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `st.error()` | 显示校验失败或权限错误原因。 |
| `auth.login()` | 调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。 |
| `st.rerun()` | 立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。 |

### 2. `app_context()`

[查看函数源码](../app.py#L97)

**当前函数的功能：** 创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |

### 3. `submit_form_action()`

[查看函数源码](../app.py#L118)

**当前函数的功能：** 工作台表单生成独立请求，调用 propose 保存确认卡片；不直接修改工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `labels.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `字典字面量.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `payload.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `sessions.begin_request()` | 在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。 |
| `sessions.claim_request()` | BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。 |
| `app_context()` | 创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |
| `storage.log_execution()` | 调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。 |
| `actions.render_result()` | 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。 |
| `sessions.finish_request()` | 校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `st.rerun()` | 立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。 |

### 4. `show_confirmations()`

[查看函数源码](../app.py#L183)

**当前函数的功能：** 展示服务器保存的冻结参数；按钮只提交 operation_id，调用 confirm_action 验证并执行。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `st.container()` | 建立分组容器，border=True 时把待确认操作围成独立卡片。 |
| `st.subheader()` | 显示当前区域的小标题。 |
| `st.caption()` | 显示辅助说明，例如 UTC 时间、模型配置或统计口径。 |
| `display.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `字典字面量.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `st.write()` | 显示文本或字段值，支持简单 Markdown。 |
| `payload.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `st.warning()` | 显示需要关注的提示，例如相似工单或未完成请求。 |
| `st.dataframe()` | 显示可交互表格，用于相似工单、工单列表或人员名单。 |
| `st.checkbox()` | 显示勾选项；此处要求用户明确接受重复建单。 |
| `st.columns()` | 创建并列布局容器，后续可在各列绘制表单、按钮或指标。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `left.button()` | 绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。 |
| `right.button()` | 绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `actions.render_result()` | 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。 |
| `st.rerun()` | 立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。 |

### 5. `show_timeline()`

[查看函数源码](../app.py#L258)

**当前函数的功能：** 读取真实 execution_events；只展示实际提取事实/工具/确认结果，不伪造模型思考过程。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `st.subheader()` | 显示当前区域的小标题。 |
| `sessions.timeline()` | 先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。 |
| `st.caption()` | 显示辅助说明，例如 UTC 时间、模型配置或统计口径。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `max()` | 选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。 |
| `enumerate()` | 遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。 |
| `字典字面量.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `event['result'].get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `st.expander()` | 创建可展开/折叠的详情区域，容纳事实、日志或处理表单。 |
| `st.json()` | 把真实参数或结果格式化为 JSON 详情供展开查看，不作为模型思考过程。 |
| `service.usage_for()` | 从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。 |

### 6. `show_chat()`

[查看函数源码](../app.py#L324)

**当前函数的功能：** 调用 begin_request/run_request 执行对话；页面刷新后从 SQLite 恢复记录、待确认和失败重试。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `st.columns()` | 创建并列布局容器，后续可在各列绘制表单、按钮或指标。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `st.subheader()` | 显示当前区域的小标题。 |
| `st.info()` | 显示普通提示，例如等待确认、无密钥或操作结果。 |
| `st.chat_message()` | 创建用户或助手消息气泡，再向其中渲染持久化的文本。 |
| `st.markdown()` | 渲染已保存的聊天文本或页面 Markdown 内容。 |
| `sessions.active_request()` | 查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。 |
| `st.warning()` | 显示需要关注的提示，例如相似工单或未完成请求。 |
| `first.button()` | 绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。 |
| `second.button()` | 绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。 |
| `sessions.abandon_request()` | 撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。 |
| `st.rerun()` | 立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `st.chat_input()` | 取得用户本轮提交的聊天文本；禁用时不能发起模型请求。 |
| `sessions.begin_request()` | 在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。 |
| `sessions.get_request()` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |
| `app_context()` | 创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。 |
| `storage.log_execution()` | 调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `st.error()` | 显示校验失败或权限错误原因。 |
| `st.spinner()` | 在耗时请求执行期间显示等待提示，退出代码块后移除。 |
| `service.run_request()` | 验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。 |
| `asyncio.run()` | 在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。 |
| `show_confirmations()` | 展示服务器保存的冻结参数；按钮只提交 operation_id，调用 confirm_action 验证并执行。 |
| `st.expander()` | 创建可展开/折叠的详情区域，容纳事实、日志或处理表单。 |
| `st.write()` | 显示文本或字段值，支持简单 Markdown。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `show_timeline()` | 读取真实 execution_events；只展示实际提取事实/工具/确认结果，不伪造模型思考过程。 |

### 7. `show_ticket_detail()`

[查看函数源码](../app.py#L421)

**当前函数的功能：** 读取真实详情和事件，显示生命周期；各表单调用 submit_form_action 进入同一确认机制。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `actions.read_ticket()` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |
| `st.error()` | 显示校验失败或权限错误原因。 |
| `st.subheader()` | 显示当前区域的小标题。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `st.write()` | 显示文本或字段值，支持简单 Markdown。 |
| `st.columns()` | 创建并列布局容器，后续可在各列绘制表单、按钮或指标。 |
| `first.metric()` | 显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。 |
| `second.metric()` | 显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。 |
| `third.metric()` | 显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。 |
| `st.info()` | 显示普通提示，例如等待确认、无密钥或操作结果。 |
| `st.caption()` | 显示辅助说明，例如 UTC 时间、模型配置或统计口径。 |
| `st.expander()` | 创建可展开/折叠的详情区域，容纳事实、日志或处理表单。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `actions.ACTION_LABELS.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `before.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `after.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `st.json()` | 把真实参数或结果格式化为 JSON 详情供展开查看，不作为模型思考过程。 |
| `st.form()` | 创建表单容器，将一组输入汇集到一次提交。 |
| `st.text_area()` | 显示多行文本框，适合填写故障描述。 |
| `st.text_input()` | 显示单行文本框并返回输入；type=password 时隐藏密码。 |
| `st.form_submit_button()` | 绘制表单提交按钮，返回本轮是否发生提交。 |
| `submit_form_action()` | 工作台表单生成独立请求，调用 propose 保存确认卡片；不直接修改工单。 |
| `sorted()` | 返回按默认次序或 key 规则排好的新列表，不原地修改原列表。 |
| `st.selectbox()` | 显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。 |
| `auth.users()` | 供可信工作台列举人员；调用 connect/public_user 去除认证资料。 |

### 8. `show_workbench()`

[查看函数源码](../app.py#L566)

**当前函数的功能：** 按权限筛选工单，提供详情、状态统计和可手工填写的建单表单，不依赖模型连通性。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `st.subheader()` | 显示当前区域的小标题。 |
| `show_confirmations()` | 展示服务器保存的冻结参数；按钮只提交 operation_id，调用 confirm_action 验证并执行。 |
| `st.expander()` | 创建可展开/折叠的详情区域，容纳事实、日志或处理表单。 |
| `st.form()` | 创建表单容器，将一组输入汇集到一次提交。 |
| `st.text_input()` | 显示单行文本框并返回输入；type=password 时隐藏密码。 |
| `st.text_area()` | 显示多行文本框，适合填写故障描述。 |
| `st.selectbox()` | 显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。 |
| `st.form_submit_button()` | 绘制表单提交按钮，返回本轮是否发生提交。 |
| `submit_form_action()` | 工作台表单生成独立请求，调用 propose 保存确认卡片；不直接修改工单。 |
| `st.columns()` | 创建并列布局容器，后续可在各列绘制表单、按钮或指标。 |
| `first.text_input()` | 显示单行文本框并返回输入；type=password 时隐藏密码。 |
| `second.text_input()` | 显示单行文本框并返回输入；type=password 时隐藏密码。 |
| `third.selectbox()` | 显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。 |
| `actions.search_tickets()` | 按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。 |
| `st.error()` | 显示校验失败或权限错误原因。 |
| `outcome.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `zip()` | 把多个序列按位置配对，关联候选文档与分数或统计列与状态。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `column.metric()` | 显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。 |
| `st.caption()` | 显示辅助说明，例如 UTC 时间、模型配置或统计口径。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `st.dataframe()` | 显示可交互表格，用于相似工单、工单列表或人员名单。 |
| `show_ticket_detail()` | 读取真实详情和事件，显示生命周期；各表单调用 submit_form_action 进入同一确认机制。 |

**匿名函数：**

- `lambda value: {'single': '单台设备', 'multiple': '多台设备', 'all': '全部设备'}[value]`：由 selectbox 的 format_func 调用，把影响范围内部值显示为中文；返回值只用于显示。

### 9. `show_admin()`

[查看函数源码](../app.py#L658)

**当前函数的功能：** 管理员创建真实工作人员与专长规则；调用 create_user 再次检查管理权限。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `st.subheader()` | 显示当前区域的小标题。 |
| `auth.users()` | 供可信工作台列举人员；调用 connect/public_user 去除认证资料。 |
| `st.dataframe()` | 显示可交互表格，用于相似工单、工单列表或人员名单。 |
| `st.form()` | 创建表单容器，将一组输入汇集到一次提交。 |
| `st.text_input()` | 显示单行文本框并返回输入；type=password 时隐藏密码。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `st.selectbox()` | 显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。 |
| `st.multiselect()` | 显示多选框，返回维修人员选择的故障专长列表。 |
| `st.form_submit_button()` | 绘制表单提交按钮，返回本轮是否发生提交。 |
| `item.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `item.strip(...).upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `models.split()` | 按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。 |
| `auth.create_user()` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `st.success()` | 显示成功或已配置状态提示。 |
| `st.error()` | 显示校验失败或权限错误原因。 |

**间接调用与回调：**

- `ROLE_LABELS.get`：由 st.selectbox 调用/注册：按映射返回对应值；这里用于显示名称或评分选择，而不是立即主动调用。

### 10. `main()`

[查看函数源码](../app.py#L722)

**当前函数的功能：** 恢复登录及选中会话，调用三个工作区；刷新不会清空 SQLite 中的对话和待确认卡片。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `st.query_params.get()` | 读取浏览器 URL 中的登录令牌或会话选择；角色还必须经数据库验证。 |
| `auth.authenticate()` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |
| `show_login()` | 显示首次管理员设置或登录/客户注册；调用 auth，角色不由聊天内容或 URL 指定。 |
| `sessions.list_threads()` | 参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。 |
| `sessions.create_thread()` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `st.subheader()` | 显示当前区域的小标题。 |
| `st.write()` | 显示文本或字段值，支持简单 Markdown。 |
| `ids.index()` | 查找选中会话在可用编号列表中的位置，作为下拉框默认选择。 |
| `st.selectbox()` | 显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。 |
| `st.button()` | 绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。 |
| `st.rerun()` | 立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。 |
| `st.caption()` | 显示辅助说明，例如 UTC 时间、模型配置或统计口径。 |
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |
| `model.startswith()` | 判断文本是否带指定前缀；此处按模型提供商选择需要读取的密钥。 |
| `os.getenv()` | 读取环境变量，可指定默认值；读取的是当前进程配置。 |
| `os.getenv(...).strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `st.success()` | 显示成功或已配置状态提示。 |
| `st.info()` | 显示普通提示，例如等待确认、无密钥或操作结果。 |
| `auth.logout()` | 调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。 |
| `st.query_params.clear()` | 清空当前 URL 参数，退出登录后不再带旧令牌和选中的会话。 |
| `app_context()` | 创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。 |
| `st.title()` | 显示页面一级标题。 |
| `st.empty()` | 创建固定位置占位容器，后续显示一次性提示时尽量保持页面结构稳定。 |
| `st.session_state.pop()` | 读取并移除一次性页面提示，避免每次重跑重复显示旧通知。 |
| `notice_box.info()` | 显示普通提示，例如等待确认、无密钥或操作结果。 |
| `st.tabs()` | 创建多个工作区标签及其容器；各标签的 Python 内容都会执行。 |
| `show_chat()` | 调用 begin_request/run_request 执行对话；页面刷新后从 SQLite 恢复记录、待确认和失败重试。 |
| `show_workbench()` | 按权限筛选工单，提供详情、状态统计和可手工填写的建单表单，不依赖模型连通性。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `show_admin()` | 管理员创建真实工作人员与专长规则；调用 create_user 再次检查管理权限。 |

**间接调用与回调：**

- `labels.get`：由 st.selectbox 调用/注册：按映射返回对应值；这里用于显示名称或评分选择，而不是立即主动调用。

## src/react_agent/actions.py

### 11. `actor_in()`

[查看函数源码](../src/react_agent/actions.py#L47)

**当前函数的功能：** 查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `PermissionError()` | 构造身份或资源归属校验失败的异常，阻止后续操作。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |

### 12. `visible()`

[查看函数源码](../src/react_agent/actions.py#L65)

**当前函数的功能：** 纯权限判断：客户只读自己的工单，工作人员可读工作台工单。

本函数没有调用其他函数，仅比较已有字段、返回固定值或返回对象本身。

### 13. `read_ticket()`

[查看函数源码](../src/react_agent/actions.py#L81)

**当前函数的功能：** 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.normalize_id()` | 用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `actor_in()` | 查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `visible()` | 纯权限判断：客户只读自己的工单，工作人员可读工作台工单。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |

### 14. `search_tickets()`

[查看函数源码](../src/react_agent/actions.py#L133)

**当前函数的功能：** 按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `datetime.strptime()` | 按 YYYY-MM-DD 解析日期，非法日期抛出 ValueError。 |
| `ValueError()` | 构造无效参数或状态异常，交给调用方捕获和显示。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `actor_in()` | 查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。 |
| `clauses.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `args.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `storage.normalize_id()` | 用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。 |
| `product_model.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `product_model.strip(...).upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

### 15. `priority_for()`

[查看函数源码](../src/react_agent/actions.py#L212)

**当前函数的功能：** 以明确业务规则计算优先级；安全故障紧急，多设备影响高，其余普通。

本函数没有调用其他函数，仅比较已有字段、返回固定值或返回对象本身。

### 16. `choose_assignee()`

[查看函数源码](../src/react_agent/actions.py#L231)

**当前函数的功能：** 从真实维修人员中按型号/故障专长筛选，SELECT 统计未关闭数量后选择负载较低者。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `candidates.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `min()` | 选择最小值；用于挑选负载较低的维修人员或限制并发上限。 |

### 17. `similar_tickets()`

[查看函数源码](../src/react_agent/actions.py#L258)

**当前函数的功能：** 只比较同客户同型号未关闭工单；用故障类别及 SequenceMatcher 做可解释的相似提示。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `SequenceMatcher()` | 建立两段故障文本的序列比较器，后续 ratio 给出相似程度。 |
| `SequenceMatcher(...).ratio()` | 计算两段故障文本的相似比例（0 到 1），并与故障类别一起判断相似单。 |
| `knowledge.classify_issue()` | 按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。 |
| `payload.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `round()` | 按指定小数位四舍五入，使相似度、费用或耗时便于展示。 |
| `matches.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |

### 18. `validate_update()`

[查看函数源码](../src/react_agent/actions.py#L297)

**当前函数的功能：** 核对工单可见性、当前状态、角色、是否分派给本人及本次字段；允许时返回 None，不允许时返回统一错误结果。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `visible()` | 纯权限判断：客户只读自己的工单，工作人员可读工作台工单。 |
| `fail()` | 通过 storage.result 构造当前操作的统一错误。 |
| `payload.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `payload.get(...).strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

### 19. `validate_update.fail()`

[查看函数源码](../src/react_agent/actions.py#L304)

**当前函数的功能：** 通过 storage.result 构造当前操作的统一错误。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |

### 20. `propose()`

[查看函数源码](../src/react_agent/actions.py#L406)

**当前函数的功能：** 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `actor_in()` | 查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `re.search()` | 查找第一处符合正则的内容；用于识别明确故障、失败反馈、禁止写操作或业务陈述。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `value.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `payload.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `clean.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `clean.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `storage.validate_create()` | 纯参数校验；通过 result 返回缺字段/长度/请求编号错误，不写数据库。 |
| `clean['product_model'].upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `knowledge.classify_issue()` | 按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。 |
| `priority_for()` | 以明确业务规则计算优先级；安全故障紧急，多设备影响高，其余普通。 |
| `choose_assignee()` | 从真实维修人员中按型号/故障专长筛选，SELECT 统计未关闭数量后选择负载较低者。 |
| `similar_tickets()` | 只比较同客户同型号未关闭工单；用故障类别及 SequenceMatcher 做可解释的相似提示。 |
| `storage.normalize_id()` | 用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。 |
| `visible()` | 纯权限判断：客户只读自己的工单，工作人员可读工作台工单。 |
| `validate_update()` | 核对工单可见性、当前状态、角色、是否分派给本人及本次字段；允许时返回 None，不允许时返回统一错误结果。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `original.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `clean.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `uuid4()` | 生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `datetime.now()` | 读取当前日期时间；传入 UTC 以统一数据库时间与有效期。 |
| `timedelta()` | 创建分钟或小时的时间差，加到当前时间后得到确认/登录的过期时间。 |
| `(datetime.now(UTC) + timedelta(minutes=15)).isoformat()` | 把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。 |
| `serialized.encode()` | 把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。 |
| `hashlib.sha256()` | 计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。 |
| `hashlib.sha256(...).hexdigest()` | 把哈希对象的结果转换为十六进制文本，用于存储与比较。 |

### 21. `pending_actions()`

[查看函数源码](../src/react_agent/actions.py#L560)

**当前函数的功能：** 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `actor_in()` | 查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |

### 22. `confirm_action()`

[查看函数源码](../src/react_agent/actions.py#L603)

**当前函数的功能：** 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `actor_in()` | 查询数据库中的活动账号及会话归属；返回账号记录，缺少有效身份或本人会话时抛出 PermissionError。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `visible()` | 纯权限判断：客户只读自己的工单，工作人员可读工作台工单。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `operation['payload'].encode()` | 把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。 |
| `hashlib.sha256()` | 计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。 |
| `hashlib.sha256(...).hexdigest()` | 把哈希对象的结果转换为十六进制文本，用于存储与比较。 |
| `similar_tickets()` | 只比较同客户同型号未关闭工单；用故障类别及 SequenceMatcher 做可解释的相似提示。 |
| `storage.insert_ticket()` | 可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。 |
| `validate_update()` | 核对工单可见性、当前状态、角色、是否分派给本人及本次字段；允许时返回 None，不允许时返回统一错误结果。 |
| `payload.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `changes.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `storage.record_change()` | 调用参数化 INSERT 在当前业务事务中保存前后快照；与工单修改一起提交。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `sessions.TicketContext()` | 按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。 |
| `sessions.TicketContext(...).model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |
| `render_result()` | 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。 |
| `transcript.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |

### 23. `render_result()`

[查看函数源码](../src/react_agent/actions.py#L819)

**当前函数的功能：** 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `outcome.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `ACTION_LABELS.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |

## src/react_agent/auth.py

### 24. `public_user()`

[查看函数源码](../src/react_agent/auth.py#L19)

**当前函数的功能：** 只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |

### 25. `get_user()`

[查看函数源码](../src/react_agent/auth.py#L39)

**当前函数的功能：** 调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `public_user()` | 只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。 |

### 26. `users()`

[查看函数源码](../src/react_agent/auth.py#L55)

**当前函数的功能：** 供可信工作台列举人员；调用 connect/public_user 去除认证资料。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `public_user()` | 只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

### 27. `password_digest()`

[查看函数源码](../src/react_agent/auth.py#L72)

**当前函数的功能：** 调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `secrets.token_hex()` | 生成不可预测的十六进制随机盐，使相同密码得到不同散列。 |
| `password.encode()` | 把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。 |
| `salt.encode()` | 把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。 |
| `hashlib.pbkdf2_hmac()` | 通过多轮加盐 HMAC 派生密码散列；这里使用 SHA256 和 600000 轮，不保存原始密码。 |
| `hashlib.pbkdf2_hmac(...).hex()` | 把派生得到的字节串转换为十六进制文本，组成密码散列记录。 |

### 28. `create_user()`

[查看函数源码](../src/react_agent/auth.py#L95)

**当前函数的功能：** 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `re.fullmatch()` | 要求整段文本符合正则；用于账号/编号校验或排除工单编号被误当设备型号。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `password_digest()` | 调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `get_user()` | 调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。 |

### 29. `login()`

[查看函数源码](../src/react_agent/auth.py#L198)

**当前函数的功能：** 调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `password_digest()` | 调用 secrets 和 PBKDF2-HMAC-SHA256 加盐散列密码，不保存明文。 |
| `digest.split()` | 按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。 |
| `hmac.compare_digest()` | 比较两个散列结果，减少普通字符串比较可能带来的时序差异。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `secrets.token_urlsafe()` | 生成可放进 URL 的高随机性登录令牌，数据库只保存其散列。 |
| `datetime.now()` | 读取当前日期时间；传入 UTC 以统一数据库时间与有效期。 |
| `timedelta()` | 创建分钟或小时的时间差，加到当前时间后得到确认/登录的过期时间。 |
| `(datetime.now(UTC) + timedelta(hours=12)).isoformat()` | 把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。 |
| `token.encode()` | 把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。 |
| `hashlib.sha256()` | 计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。 |
| `hashlib.sha256(...).hexdigest()` | 把哈希对象的结果转换为十六进制文本，用于存储与比较。 |
| `public_user()` | 只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。 |

### 30. `authenticate()`

[查看函数源码](../src/react_agent/auth.py#L244)

**当前函数的功能：** 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `token.encode()` | 把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。 |
| `hashlib.sha256()` | 计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。 |
| `hashlib.sha256(...).hexdigest()` | 把哈希对象的结果转换为十六进制文本，用于存储与比较。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `public_user()` | 只返回账号公开字段；json.loads 还原维修人员的型号/故障专长，不返回密码散列。 |

### 31. `logout()`

[查看函数源码](../src/react_agent/auth.py#L265)

**当前函数的功能：** 调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `token.encode()` | 把字符串编码为字节，供密码派生或 SHA256 摘要计算使用。 |
| `hashlib.sha256()` | 计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。 |
| `hashlib.sha256(...).hexdigest()` | 把哈希对象的结果转换为十六进制文本，用于存储与比较。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

## src/react_agent/graph.py

### 32. `trim_conversation()`

[查看函数源码](../src/react_agent/graph.py#L42)

**当前函数的功能：** 按 HumanMessage 划分完整轮次再裁剪，不拆开 AI 工具调用与 ToolMessage 配对。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `groups.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `groups[-1].append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `reversed()` | 逆序遍历轮次，使裁剪先选择最近的对话。 |
| `message.model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `selected.insert()` | 在指定位置插入元素；此处把倒序选中的轮次插回开头，恢复时间顺序。 |

### 33. `prepare()`

[查看函数源码](../src/react_agent/graph.py#L65)

**当前函数的功能：** 从 sessions.get_thread 恢复事实和摘要，用 RemoveMessage 替换裁剪后的消息，重置本轮工具证据。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `trim_conversation()` | 按 HumanMessage 划分完整轮次再裁剪，不拆开 AI 工具调用与 ToolMessage 配对。 |
| `RemoveMessage()` | 构造删除旧消息的指令，交给 add_messages 合并器处理；本处用于整体替换裁剪后的历史。 |

### 34. `call_model()`

[查看函数源码](../src/react_agent/graph.py#L113)

**当前函数的功能：** 读取可信身份、结构化事实与摘要，预检预算，调用带工具 schema 的模型；记录真实或估算用量，对指定瞬时错误最多再尝试一次。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `uuid4()` | 生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `asyncio.to_thread()` | 把传入的同步函数放到工作线程执行并异步等待，避免 SQLite 操作阻塞检查点所在的事件循环。 |
| `datetime.now()` | 读取当前日期时间；传入 UTC 以统一数据库时间与有效期。 |
| `datetime.now(...).isoformat()` | 把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。 |
| `context.system_prompt.format()` | 把 system_time 填入系统提示模板，不从用户消息决定角色或权限。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `message.model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `load_chat_model()` | 按 provider/model 配置创建支持工具调用的聊天模型客户端；创建对象时不发起本轮模型推理。 |
| `load_chat_model(...).bind_tools()` | 把工具的名称、说明和参数 schema 绑定给模型；真实工具执行仍由 execute_tools 完成。 |
| `hasattr()` | 检查对象是否支持某个属性或方法，兼容真实模型与简化测试模型。 |
| `model.bind()` | 给模型调用绑定 max_tokens 等生成参数；不在这一行发起网络推理。 |
| `range()` | 产生整数序列，供有界重试、模拟轮次或并发任务循环使用。 |
| `time.monotonic()` | 读取单调递增时间，计算耗时，不受系统日期调整影响。 |
| `model.ainvoke()` | 异步调用已配置的模型，返回助手文本或工具请求；测试模型则返回预设响应。 |
| `asyncio.wait_for()` | 等待一个异步调用并施加单次超时；超过限制会触发超时异常。 |
| `type()` | 取得对象的类型；此处主要用异常类型名记录错误类别。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `asyncio.sleep()` | 异步等待短暂退避时间，不阻塞其他任务；此处仅在允许重试的瞬时错误后使用。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `usage.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `get_message_text()` | 从模型或工具消息中提取文本，统一处理字符串内容和内容块列表。 |
| `response.response_metadata.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |

**间接调用与回调：**

- `sessions.get_thread`：由 asyncio.to_thread 调用/注册：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
- `auth.get_user`：由 asyncio.to_thread 调用/注册：调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。
- `storage.log_execution`：由 asyncio.to_thread 调用/注册：调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。

### 35. `execute_tools()`

[查看函数源码](../src/react_agent/graph.py#L255)

**当前函数的功能：** 逐个检查模型请求的工具名称、参数及次数预算，执行已登记工具，生成对应 ToolMessage 并保存真实日志；成功查询到工单时更新当前工单记忆。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `time.monotonic()` | 读取单调递增时间，计算耗时，不受系统日期调整影响。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `asyncio.to_thread()` | 把传入的同步函数放到工作线程执行并异步等待，避免 SQLite 操作阻塞检查点所在的事件循环。 |
| `set()` | 构造不重复元素集合，用于检查未知参数、工具配对或唯一查询词。 |
| `TOOL_MAP[name].ainvoke()` | 调用名称对应的 StructuredTool，校验模型参数后进入真实 Python 工具函数，支持当前运行上下文。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `ToolMessage()` | 构造工具返回消息，通过 tool_call_id 对应模型上一条工具请求。 |
| `messages.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `facts.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `outcome.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |

**间接调用与回调：**

- `storage.log_execution`：由 asyncio.to_thread 调用/注册：调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。
- `sessions.get_thread`：由 asyncio.to_thread 调用/注册：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
- `sessions.save_memory`：由 asyncio.to_thread 调用/注册：用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。

### 36. `render_faq()`

[查看函数源码](../src/react_agent/graph.py#L330)

**当前函数的功能：** 用可信 FAQ 返回值选择一个新步骤并引用来源；调用方负责保存 last_suggested_step。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `outcome.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |

### 37. `finalize()`

[查看函数源码](../src/react_agent/graph.py#L379)

**当前函数的功能：** 最终业务文本来自工具事实或确定性追问；模型自称成功、编造状态/FAQ 的文字不会作为业务结果展示。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `outcome.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `actions.read_ticket()` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |
| `refreshed.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `actions.render_result()` | 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。 |
| `lines.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `render_faq()` | 用可信 FAQ 返回值选择一个新步骤并引用来源；调用方负责保存 last_suggested_step。 |
| `sessions.save_memory()` | 用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。 |
| `storage.log_execution()` | 调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |

### 38. `route_model_output()`

[查看函数源码](../src/react_agent/graph.py#L464)

**当前函数的功能：** 有 tool_calls 就交给受限执行器，否则进入可信回复节点。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |

### 39. `route_tools()`

[查看函数源码](../src/react_agent/graph.py#L478)

**当前函数的功能：** 工具结果交回模型继续选择工具；最终业务文本仍由 finalize 根据可信证据生成。

本函数没有调用其他函数，仅比较已有字段、返回固定值或返回对象本身。

本函数只返回下一节点名称；LangGraph 随后才调用 call_model，不是本函数直接调用模型。

### 40. `build_graph()`

[查看函数源码](../src/react_agent/graph.py#L498)

**当前函数的功能：** 用 StateGraph 装配模型—工具循环；传入官方 AsyncSqliteSaver 后支持跨进程恢复。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `StateGraph()` | 创建状态图构建器，声明图状态、输入结构和应用上下文类型。 |
| `builder.add_node()` | 把节点名称与处理函数登记到图中；注册时不会立即执行该函数。 |
| `builder.add_edge()` | 登记固定的节点执行顺序，例如开始后进入 prepare。 |
| `builder.add_conditional_edges()` | 登记路由函数，根据当前状态选择下一节点，而不是固定一条边。 |
| `builder.compile()` | 把已经登记的节点和边编译为可调用图，附加检查点保存器。 |

**间接调用与回调：**

- `prepare`：由 builder.add_node 调用/注册：从 sessions.get_thread 恢复事实和摘要，用 RemoveMessage 替换裁剪后的消息，重置本轮工具证据。
- `call_model`：由 builder.add_node 调用/注册：读取可信身份、结构化事实与摘要，预检预算，调用带工具 schema 的模型；记录真实或估算用量，对指定瞬时错误最多再尝试一次。
- `execute_tools`：由 builder.add_node 调用/注册：逐个检查模型请求的工具名称、参数及次数预算，执行已登记工具，生成对应 ToolMessage 并保存真实日志；成功查询到工单时更新当前工单记忆。
- `finalize`：由 builder.add_node 调用/注册：最终业务文本来自工具事实或确定性追问；模型自称成功、编造状态/FAQ 的文字不会作为业务结果展示。
- `route_model_output`：由 builder.add_conditional_edges 调用/注册：有 tool_calls 就交给受限执行器，否则进入可信回复节点。
- `route_tools`：由 builder.add_conditional_edges 调用/注册：工具结果交回模型继续选择工具；最终业务文本仍由 finalize 根据可信证据生成。

## src/react_agent/knowledge.py

### 41. `classify_issue()`

[查看函数源码](../src/react_agent/knowledge.py#L33)

**当前函数的功能：** 按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `text.casefold()` | 进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `SYNONYMS.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `max()` | 选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。 |

**间接调用与回调：**

- `scores.get`：由 max 调用/注册：按映射返回对应值；这里用于显示名称或评分选择，而不是立即主动调用。

### 42. `model_in()`

[查看函数源码](../src/react_agent/knowledge.py#L54)

**当前函数的功能：** 用正则提取明确型号；多个不同型号时返回 None，要求调用者追问。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `text.upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `re.findall()` | 提取所有匹配项，形成设备型号、英文词或中文片段列表。 |
| `re.fullmatch()` | 要求整段文本符合正则；用于账号/编号校验或排除工单编号被误当设备型号。 |
| `dict.fromkeys()` | 用字典键的唯一性去重并保留首次出现顺序，随后可转回列表。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

### 43. `tokenize()`

[查看函数源码](../src/react_agent/knowledge.py#L77)

**当前函数的功能：** 用正则产生英文词和中文双字片段，供 BM25 做本地全文排序。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `text.casefold()` | 进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。 |
| `re.findall()` | 提取所有匹配项，形成设备型号、英文词或中文片段列表。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `max()` | 选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。 |
| `range()` | 产生整数序列，供有界重试、模拟轮次或并发任务循环使用。 |
| `tokens.extend()` | 把另一序列的每个元素追加到列表，合并消息或分词结果。 |

### 44. `bm25()`

[查看函数源码](../src/react_agent/knowledge.py#L97)

**当前函数的功能：** 调用 tokenize/Counter/log 计算 BM25；只在已经按型号过滤的资料中排序。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tokenize()` | 用正则产生英文词和中文双字片段，供 BM25 做本地全文排序。 |
| `Counter()` | 统计每个词/片段的出现频次，形成 BM25 的文档词频。 |
| `bag.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `set()` | 构造不重复元素集合，用于检查未知参数、工具配对或唯一查询词。 |
| `math.log()` | 计算 BM25 逆文档频率中的自然对数，让较少见的查询词获得更高区分度。 |
| `enumerate()` | 遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。 |

### 45. `search()`

[查看函数源码](../src/react_agent/knowledge.py#L142)

**当前函数的功能：** 调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `model_in()` | 用正则提取明确型号；多个不同型号时返回 None，要求调用者追问。 |
| `device_model.upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `(device_model or explicit or '').strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `(device_model or explicit or '').strip(...).upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `classify_issue()` | 按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。 |
| `query.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `(storage.ROOT / 'data/faq.json').read_text()` | 读取 UTF-8 文本，供解析 FAQ 或固定评测用例。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `bm25()` | 调用 tokenize/Counter/log 计算 BM25；只在已经按型号过滤的资料中排序。 |
| `zip()` | 把多个序列按位置配对，关联候选文档与分数或统计列与状态。 |
| `word.casefold()` | 进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。 |
| `query.casefold()` | 进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `round()` | 按指定小数位四舍五入，使相似度、费用或耗时便于展示。 |
| `ranked.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `sorted()` | 返回按默认次序或 key 规则排好的新列表，不原地修改原列表。 |
| `all()` | 检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。 |

**匿名函数：**

- `lambda entry: -entry['score']`：由 sorted 的 key 调用，返回负分数，让检索结果按分数从高到低排列。

## src/react_agent/service.py

### 46. `usage_for()`

[查看函数源码](../src/react_agent/service.py#L26)

**当前函数的功能：** 从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `usage.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `starts.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `row.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |

### 47. `monetary_cost()`

[查看函数源码](../src/react_agent/service.py#L62)

**当前函数的功能：** 仅在应用设置每百万 token 单价时计算估算成本；不把未知价格写成零。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `float()` | 把配置的单价文本转换为浮点数，转换失败交给异常分支处理。 |
| `round()` | 按指定小数位四舍五入，使相似度、费用或耗时便于展示。 |

### 48. `run_request()`

[查看函数源码](../src/react_agent/service.py#L105)

**当前函数的功能：** 验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `auth.get_user()` | 调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。 |
| `PermissionError()` | 构造身份或资源归属校验失败的异常，阻止后续操作。 |
| `sessions.get_request()` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |
| `sessions.claim_request()` | BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。 |
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |
| `sessions.timeline()` | 先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。 |
| `usage_for()` | 从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。 |
| `time.monotonic()` | 读取单调递增时间，计算耗时，不受系统日期调整影响。 |
| `storage.database_path()` | 调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `AsyncSqliteSaver.from_conn_string()` | 打开官方异步 SQLite 检查点管理器，保存/恢复图状态；async with 结束时释放连接。 |
| `build_graph()` | 用 StateGraph 装配模型—工具循环；传入官方 AsyncSqliteSaver 后支持跨进程恢复。 |
| `agent.aget_state()` | 读取 thread_id 对应的最新图状态及待执行节点，判断应开始新轮次、续跑还是复用完成结果。 |
| `snapshot.values.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `HumanMessage()` | 构造用户消息；固定 id 可让检查点重试合并同一输入，避免重复追加。 |
| `asyncio.timeout()` | 为整个异步代码块设置总时间限制，避免单轮 Agent 长期不结束。 |
| `agent.astream()` | 真正执行或恢复状态图，按节点更新流返回消息和最终结果。 |
| `update.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `node.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `messages.extend()` | 把另一序列的每个元素追加到列表，合并消息或分词结果。 |
| `message.model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |
| `round()` | 按指定小数位四舍五入，使相似度、费用或耗时便于展示。 |
| `monetary_cost()` | 仅在应用设置每百万 token 单价时计算估算成本；不把未知价格写成零。 |
| `sessions.finish_request()` | 校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。 |
| `type()` | 取得对象的类型；此处主要用异常类型名记录错误类别。 |

## src/react_agent/sessions.py

### 49. `create_thread()`

[查看函数源码](../src/react_agent/sessions.py#L41)

**当前函数的功能：** 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `auth.get_user()` | 调用 connect 和 public_user 查询有效用户；所有工具在执行时重新读取角色。 |
| `PermissionError()` | 构造身份或资源归属校验失败的异常，阻止后续操作。 |
| `uuid4()` | 生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

### 50. `get_thread()`

[查看函数源码](../src/react_agent/sessions.py#L65)

**当前函数的功能：** 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `PermissionError()` | 构造身份或资源归属校验失败的异常，阻止后续操作。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `TicketContext()` | 按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。 |
| `TicketContext(...).model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |

### 51. `list_threads()`

[查看函数源码](../src/react_agent/sessions.py#L87)

**当前函数的功能：** 参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

### 52. `save_memory()`

[查看函数源码](../src/react_agent/sessions.py#L108)

**当前函数的功能：** 用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `TicketContext()` | 按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。 |
| `TicketContext(...).model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

### 53. `extract_facts()`

[查看函数源码](../src/react_agent/sessions.py#L130)

**当前函数的功能：** 调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `TicketContext()` | 按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。 |
| `TicketContext(...).model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |
| `knowledge.model_in()` | 用正则提取明确型号；多个不同型号时返回 None，要求调用者追问。 |
| `knowledge.classify_issue()` | 按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。 |
| `re.search()` | 查找第一处符合正则的内容；用于识别明确故障、失败反馈、禁止写操作或业务陈述。 |
| `tried.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `dict.fromkeys()` | 用字典键的唯一性去重并保留首次出现顺序，随后可转回列表。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |

### 54. `begin_request()`

[查看函数源码](../src/react_agent/sessions.py#L189)

**当前函数的功能：** 在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `text.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `ValueError()` | 构造无效参数或状态异常，交给调用方捕获和显示。 |
| `get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `uuid4()` | 生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `extract_facts()` | 调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `transcript.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |

### 55. `get_request()`

[查看函数源码](../src/react_agent/sessions.py#L262)

**当前函数的功能：** 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `PermissionError()` | 构造身份或资源归属校验失败的异常，阻止后续操作。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |

### 56. `active_request()`

[查看函数源码](../src/react_agent/sessions.py#L283)

**当前函数的功能：** 查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `get_request()` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |

### 57. `claim_request()`

[查看函数源码](../src/react_agent/sessions.py#L304)

**当前函数的功能：** BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `uuid4()` | 生成随机 UUID，分别用于会话、请求、确认操作、消息或执行尝试的唯一标识。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `PermissionError()` | 构造身份或资源归属校验失败的异常，阻止后续操作。 |
| `time.time()` | 读取当前 Unix 时间戳，用于比较请求租约是否到期。 |
| `ValueError()` | 构造无效参数或状态异常，交给调用方捕获和显示。 |

### 58. `finish_request()`

[查看函数源码](../src/react_agent/sessions.py#L338)

**当前函数的功能：** 校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `ValueError()` | 构造无效参数或状态异常，交给调用方捕获和显示。 |
| `storage.encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `storage.now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `transcript.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |

### 59. `abandon_request()`

[查看函数源码](../src/react_agent/sessions.py#L393)

**当前函数的功能：** 撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `time.time()` | 读取当前 Unix 时间戳，用于比较请求租约是否到期。 |

### 60. `timeline()`

[查看函数源码](../src/react_agent/sessions.py#L421)

**当前函数的功能：** 先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |

## src/react_agent/storage.py

### 61. `now()`

[查看函数源码](../src/react_agent/storage.py#L21)

**当前函数的功能：** 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `datetime.now()` | 读取当前日期时间；传入 UTC 以统一数据库时间与有效期。 |
| `datetime.now(...).isoformat()` | 把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。 |

### 62. `encode()`

[查看函数源码](../src/react_agent/storage.py#L30)

**当前函数的功能：** 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `json.dumps()` | 把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。 |

### 63. `result()`

[查看函数源码](../src/react_agent/storage.py#L39)

**当前函数的功能：** 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `error.upper()` | 把字母转为大写，统一设备型号或错误码。 |

### 64. `database_path()`

[查看函数源码](../src/react_agent/storage.py#L62)

**当前函数的功能：** 调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `os.getenv()` | 读取环境变量，可指定默认值；读取的是当前进程配置。 |
| `Path()` | 构造文件路径对象，便于拼接路径、判断绝对路径和读取本地文件。 |
| `Path(...).expanduser()` | 把路径中的 ~ 展开为当前用户目录。 |
| `target.is_absolute()` | 判断数据库路径是否已是绝对路径，否则相对项目根目录解析。 |

### 65. `migrate()`

[查看函数源码](../src/react_agent/storage.py#L76)

**当前函数的功能：** 在写事务中建表、按 PRAGMA table_info 增列；不删除或重新编号原工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `additions.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `db.commit()` | 提交本次迁移事务，使新增表、列及版本号一起生效。 |

### 66. `connect()`

[查看函数源码](../src/react_agent/storage.py#L173)

**当前函数的功能：** 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `database_path()` | 调用 getenv/Path 确定数据库位置；相对路径以项目根目录为基准。 |
| `target.parent.mkdir()` | 创建输出或数据库父目录；parents/exist_ok 允许补齐父级并复用现有目录。 |
| `sqlite3.connect()` | 打开指定 SQLite 文件连接；迁移测试也用它建立原始旧表，绕开应用迁移逻辑。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `migrate()` | 在写事务中建表、按 PRAGMA table_info 增列；不删除或重新编号原工单。 |
| `db.close()` | 关闭 SQLite 连接，释放文件和事务资源；finally 保证异常时也执行。 |

**装饰器：**

- `contextmanager`：把含 yield 的 connect 函数转换为 with 上下文管理器，进入时打开连接，退出时继续执行提交/回滚及关闭流程。

### 67. `normalize_id()`

[查看函数源码](../src/react_agent/storage.py#L196)

**当前函数的功能：** 用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `ticket_id.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `re.fullmatch()` | 要求整段文本符合正则；用于账号/编号校验或排除工单编号被误当设备型号。 |
| `int()` | 转换为整数；在工单编号中去掉数字前导零，再由格式化补成规范编号。 |

### 68. `validate_create()`

[查看函数源码](../src/react_agent/storage.py#L216)

**当前函数的功能：** 纯参数校验；通过 result 返回缺字段/长度/请求编号错误，不写数据库。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `values.items()` | 遍历键和值的配对，供参数整理、过滤条件或字段展示使用。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `v.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `product_model.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `issue_description.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `request_id.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |

### 69. `record_change()`

[查看函数源码](../src/react_agent/storage.py#L249)

**当前函数的功能：** 调用参数化 INSERT 在当前业务事务中保存前后快照；与工单修改一起提交。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

### 70. `insert_ticket()`

[查看函数源码](../src/react_agent/storage.py#L281)

**当前函数的功能：** 可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `payload.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `ticket.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `tuple()` | 把值序列固定为元组，以便作为 SQL 的位置参数传入。 |
| `record_change()` | 调用参数化 INSERT 在当前业务事务中保存前后快照；与工单修改一起提交。 |

### 71. `create_ticket()`

[查看函数源码](../src/react_agent/storage.py#L346)

**当前函数的功能：** 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `validate_create()` | 纯参数校验；通过 result 返回缺字段/长度/请求编号错误，不写数据库。 |
| `connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `product_model.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `issue_description.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `request_id.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `insert_ticket()` | 可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。 |

### 72. `get_ticket_status()`

[查看函数源码](../src/react_agent/storage.py#L377)

**当前函数的功能：** 可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `normalize_id()` | 用 fullmatch 校验编号，int/格式化把 t1 规范成 T0001；不访问数据库。 |
| `result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `db.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |

### 73. `list_tickets()`

[查看函数源码](../src/react_agent/storage.py#L408)

**当前函数的功能：** 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

### 74. `log_execution()`

[查看函数源码](../src/react_agent/storage.py#L424)

**当前函数的功能：** 调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `encode()` | 调用 json.dumps 生成稳定 JSON；用于参数绑定、持久化和审计。 |
| `now()` | 返回带时区的 UTC 时间；调用 datetime.now/isoformat，供审计与有效期比较。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

## src/react_agent/tools.py

### 75. `search_faq()`

[查看函数源码](../src/react_agent/tools.py#L18)

**当前函数的功能：** 按确切型号、故障类别检索本地 FAQ，返回来源和未尝试步骤；无型号先追问，无匹配不能编造。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `memory.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `device_model.upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `knowledge.search()` | 调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。 |

### 76. `create_ticket()`

[查看函数源码](../src/react_agent/tools.py#L58)

**当前函数的功能：** 提出建单确认卡片（不会写工单）；impact 为 single/multiple/all，必填型号和用户原始故障描述。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

注意同名函数：这里是模型工具，只提出卡片；storage.create_ticket 是可信内部兼容入口，未暴露给模型。

### 77. `get_ticket_status()`

[查看函数源码](../src/react_agent/tools.py#L79)

**当前函数的功能：** 按权限查询真实工单和处理历史；编号只能来自用户输入或已查询到的真实记录。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.read_ticket()` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |

### 78. `search_tickets()`

[查看函数源码](../src/react_agent/tools.py#L89)

**当前函数的功能：** 按编号、型号、状态及 YYYY-MM-DD 起止日期查找工单；客户始终只能查自己的历史工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.search_tickets()` | 按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。 |

### 79. `update_ticket_status()`

[查看函数源码](../src/react_agent/tools.py#L114)

**当前函数的功能：** 提出工单状态流转；检查当前状态与权限，需用户点击确认后生效。处理人来自应用身份。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

### 80. `supplement_ticket()`

[查看函数源码](../src/react_agent/tools.py#L128)

**当前函数的功能：** 提出补充故障描述、联系方式或设备信息；不覆盖原始故障，确认后追加并记录审计。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

### 81. `cancel_ticket()`

[查看函数源码](../src/react_agent/tools.py#L149)

**当前函数的功能：** 提出取消尚在待处理的工单；已开始维修不可取消，需页面确认。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

### 82. `assign_ticket()`

[查看函数源码](../src/react_agent/tools.py#L163)

**当前函数的功能：** 客服/管理员提出分派给已有维修账号；建单时也会按型号、故障专长和负载自动推荐人员。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

### 83. `set_ticket_priority()`

[查看函数源码](../src/react_agent/tools.py#L177)

**当前函数的功能：** 客服/管理员提出将优先级调整为普通、高、紧急之一，需要确认并保留处理说明。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

### 84. `handoff_ticket()`

[查看函数源码](../src/react_agent/tools.py#L193)

**当前函数的功能：** 现有工单申请人工接管并保存原因；没有工单时先建议用户确认建单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

### 85. `record_ticket_context()`

[查看函数源码](../src/react_agent/tools.py#L217)

**当前函数的功能：** 以用户原文 evidence 保存型号/故障/已尝试步骤；字段必须出现在证据中，不接受推断出的工单编号或权限。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_runtime()` | 读取 LangGraph 为当前节点/工具注入的运行上下文；身份从这里取得而非从模型参数取得。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `storage.result()` | 统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。 |
| `value.casefold()` | 进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。 |
| `evidence.casefold()` | 进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。 |
| `device_model.upper()` | 把字母转为大写，统一设备型号或错误码。 |
| `knowledge.classify_issue()` | 按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。 |
| `dict.fromkeys()` | 用字典键的唯一性去重并保留首次出现顺序，随后可转回列表。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `sessions.save_memory()` | 用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。 |

## src/react_agent/utils.py

### 86. `get_message_text()`

[查看函数源码](../src/react_agent/utils.py#L16)

**当前函数的功能：** 从模型或工具消息中提取文本，统一处理字符串内容和内容块列表。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `c.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |

### 87. `get_tool_result()`

[查看函数源码](../src/react_agent/utils.py#L28)

**当前函数的功能：** 把工具消息还原为 Python 数据：空列表仍返回空列表，合法 JSON 解码为结构化对象，普通文本包装为 message 字段。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `get_message_text()` | 从模型或工具消息中提取文本，统一处理字符串内容和内容块列表。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |

### 88. `load_chat_model()`

[查看函数源码](../src/react_agent/utils.py#L45)

**当前函数的功能：** 按 provider/model 配置创建支持工具调用的聊天模型客户端；创建对象时不发起本轮模型推理。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `fully_specified_name.split()` | 按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。 |
| `ValueError()` | 构造无效参数或状态异常，交给调用方捕获和显示。 |
| `init_chat_model()` | 根据 provider/model 创建聊天模型客户端并设置温度、超时和 SDK 重试参数；创建客户端本身不等于发起推理。 |

## scripts/evaluate.py

### 89. `OfflineModel.__init__()`

[查看函数源码](../scripts/evaluate.py#L40)

**当前函数的功能：** 根据场景定义构造响应队列；最终故意虚构状态以检验可信回复。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `enumerate()` | 遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `messages.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `iter()` | 把固定响应列表转成迭代器，让脚本模型逐条返回消息。 |

### 90. `OfflineModel.bind_tools()`

[查看函数源码](../scripts/evaluate.py#L60)

**当前函数的功能：** 返回测试模型本身；真实工具仍由图执行器调用。

本函数没有调用其他函数，仅比较已有字段、返回固定值或返回对象本身。

### 91. `OfflineModel.ainvoke()`

[查看函数源码](../scripts/evaluate.py#L68)

**当前函数的功能：** 返回下一条固定消息，序列耗尽表明测试模型和执行流程不符。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `next()` | 取迭代器的下一项；脚本模型用它取响应，页面测试用它定位匹配按钮。 |

### 92. `answer_consistent()`

[查看函数源码](../scripts/evaluate.py#L82)

**当前函数的功能：** 用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `re.finditer()` | 逐项返回匹配对象，用于从最终回复提取要与数据库核对的状态陈述。 |
| `match.groups()` | 返回正则捕获组，如工单编号和声称的状态。 |
| `claims.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `re.search()` | 查找第一处符合正则的内容；用于识别明确故障、失败反馈、禁止写操作或业务陈述。 |
| `item.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |

### 93. `check_turn()`

[查看函数源码](../scripts/evaluate.py#L138)

**当前函数的功能：** 比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `expected.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `answer.strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `bool()` | 转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。 |
| `item.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `answer_consistent()` | 用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。 |
| `all()` | 检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。 |
| `outcome.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `checks.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |

### 94. `seed_database()`

[查看函数源码](../scripts/evaluate.py#L281)

**当前函数的功能：** 为每个隔离评测创建账号和可选已知工单；种子是测试前置条件，不计为 Agent 完成。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `auth.create_user()` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `case.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `seed.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `storage.insert_ticket()` | 可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。 |

### 95. `run_case()`

[查看函数源码](../scripts/evaluate.py#L336)

**当前函数的功能：** 逐轮运行真正应用服务，测试驱动器模拟确认按钮；记录确认前后快照、工具轨迹和用量。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `asyncio.to_thread()` | 把传入的同步函数放到工作线程执行并异步等待，避免 SQLite 操作阻塞检查点所在的事件循环。 |
| `case.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `sessions.create_thread()` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |
| `enumerate()` | 遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `sessions.begin_request()` | 在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。 |
| `OfflineModel()` | 构造离线脚本模型：按本用例返回预设工具请求，再故意给出虚构成功文字；真实工具和执行层仍运行。 |
| `run_request()` | 验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。 |
| `sessions.timeline()` | 先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。 |
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `turn.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `confirmations.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `actions.render_result()` | 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。 |
| `reply_snapshots.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |
| `check_turn()` | 比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。 |
| `turn['expect'].get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `assessed['checks'].values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `all()` | 检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。 |
| `report['turns'].append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |

**间接调用与回调：**

- `seed_database`：由 asyncio.to_thread 调用/注册：为每个隔离评测创建账号和可选已知工单；种子是测试前置条件，不计为 Agent 完成。

### 96. `summarize()`

[查看函数源码](../scripts/evaluate.py#L510)

**当前函数的功能：** 从逐轮报告计算业务成功率、状态一致率、工具合法率、耗时与 token；保留分母。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `result.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `turn['output'].get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `turn['output'].get(...).get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `statistics.mean()` | 计算全部已运行轮次的平均执行耗时。 |
| `round()` | 按指定小数位四舍五入，使相似度、费用或耗时便于展示。 |

### 97. `main()`

[查看函数源码](../scripts/evaluate.py#L605)

**当前函数的功能：** 解析 CLI，按有限并发运行隔离用例并增量保存；offline 与 live 的证据明确分开。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `argparse.ArgumentParser()` | 构造命令行参数解析器，生成帮助信息并校验参数。 |
| `parser.add_argument()` | 登记 mode、case、output、concurrency 等可用命令行选项。 |
| `parser.parse_args()` | 解析用户实际传入的命令行参数，返回可按属性读取的配置。 |
| `load_dotenv()` | 从 .env 加载配置到进程环境，默认不覆盖已经存在的环境变量。 |
| `(storage.ROOT / 'data/eval_cases.json').read_text()` | 读取 UTF-8 文本，供解析 FAQ 或固定评测用例。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `args.case.split()` | 按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。 |
| `parser.error()` | 输出无效参数错误并终止脚本，避免把空用例集合误报为通过。 |
| `Path()` | 构造文件路径对象，便于拼接路径、判断绝对路径和读取本地文件。 |
| `output.parent.mkdir()` | 创建输出或数据库父目录；parents/exist_ok 允许补齐父级并复用现有目录。 |
| `datetime.now()` | 读取当前日期时间；传入 UTC 以统一数据库时间与有效期。 |
| `datetime.now(...).isoformat()` | 把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。 |
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `path.relative_to()` | 把路径转换为相对项目根目录的路径，作为评测源码指纹的键。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `path.read_bytes()` | 读取源文件的原始字节，生成可复查的 SHA256 指纹。 |
| `hashlib.sha256()` | 计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。 |
| `hashlib.sha256(...).hexdigest()` | 把哈希对象的结果转换为十六进制文本，用于存储与比较。 |
| `storage.ROOT.glob()` | 枚举符合模式的源文件，形成评测时记录指纹的文件清单。 |
| `sorted()` | 返回按默认次序或 key 规则排好的新列表，不原地修改原列表。 |
| `Context(...).model.startswith()` | 判断文本是否带指定前缀；此处按模型提供商选择需要读取的密钥。 |
| `os.getenv()` | 读取环境变量，可指定默认值；读取的是当前进程配置。 |
| `os.getenv(...).strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `json.dumps()` | 把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。 |
| `output.write_text()` | 把当前报告写入本地文件，以便中途或完成后复查。 |
| `importlib.import_module()` | 按模块名导入模块；评测/测试用来替换模型加载入口，不加载用户输入的任意模块。 |
| `min()` | 选择最小值；用于挑选负载较低的维修人员或限制并发上限。 |
| `max()` | 选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。 |
| `asyncio.Semaphore()` | 创建异步信号量，限制同时运行的场景数量。 |
| `tempfile.TemporaryDirectory()` | 创建隔离的临时目录，with 退出时自动清理评测数据库。 |
| `evaluate()` | 受信号量限制运行一个用例并增量写报告；并发用例使用不同 SQLite 文件。 |
| `asyncio.gather()` | 并发等待多个场景协程；具体并发数量仍由 Semaphore 控制。 |
| `summarize()` | 从逐轮报告计算业务成功率、状态一致率、工具合法率、耗时与 token；保留分母。 |
| `all()` | 检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。 |
| `print()` | 向终端输出评测进度、证据或结果，便于观察脚本执行情况。 |

**匿名函数：**

- `lambda name: model_map[name]`：仅在离线评测期间替换模型加载器，按场景键取得已准备好的 OfflineModel。

### 98. `main.evaluate()`

[查看函数源码](../scripts/evaluate.py#L691)

**当前函数的功能：** 受信号量限制运行一个用例并增量写报告；并发用例使用不同 SQLite 文件。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `Path()` | 构造文件路径对象，便于拼接路径、判断绝对路径和读取本地文件。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `run_case()` | 逐轮运行真正应用服务，测试驱动器模拟确认按钮；记录确认前后快照、工具轨迹和用量。 |
| `type()` | 取得对象的类型；此处主要用异常类型名记录错误类别。 |
| `report['cases'].append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `report['cases'].sort()` | 按 key 原地排序列表；评测报告用它保持用例编号的次序。 |
| `json.dumps()` | 把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。 |
| `output.write_text()` | 把当前报告写入本地文件，以便中途或完成后复查。 |
| `print()` | 向终端输出评测进度、证据或结果，便于观察脚本执行情况。 |

**匿名函数：**

- `lambda item: item['id']`：由列表 sort 调用，按用例编号保持报告顺序，不改变用例结果。

## scripts/smoke_model.py

### 99. `main()`

[查看函数源码](../scripts/smoke_model.py#L39)

**当前函数的功能：** 做最小真实连接验收：强制模型选择 FAQ 工具，在本地执行工具，再让模型根据结果回答。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `load_dotenv()` | 从 .env 加载配置到进程环境，默认不覆盖已经存在的环境变量。 |
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |
| `context.model.startswith()` | 判断文本是否带指定前缀；此处按模型提供商选择需要读取的密钥。 |
| `os.getenv()` | 读取环境变量，可指定默认值；读取的是当前进程配置。 |
| `os.getenv(...).strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |
| `print()` | 向终端输出评测进度、证据或结果，便于观察脚本执行情况。 |
| `load_chat_model()` | 按 provider/model 配置创建支持工具调用的聊天模型客户端；创建对象时不发起本轮模型推理。 |
| `HumanMessage()` | 构造用户消息；固定 id 可让检查点重试合并同一输入，避免重复追加。 |
| `model.bind_tools()` | 把工具的名称、说明和参数 schema 绑定给模型；真实工具执行仍由 execute_tools 完成。 |
| `model.bind_tools(...).ainvoke()` | 异步调用已配置的模型，返回助手文本或工具请求；测试模型则返回预设响应。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `RuntimeError()` | 构造执行/协议异常；测试中也用于模拟中断，不是业务成功结果。 |
| `search()` | 调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。 |
| `result.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `json.dumps()` | 把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。 |
| `ToolMessage()` | 构造工具返回消息，通过 tool_call_id 对应模型上一条工具请求。 |
| `model.ainvoke()` | 异步调用已配置的模型，返回助手文本或工具请求；测试模型则返回预设响应。 |
| `get_message_text()` | 从模型或工具消息中提取文本，统一处理字符串内容和内容块列表。 |
| `get_message_text(...).strip()` | 去除文本两端空白，规范输入或判断是否只含空白。 |

## tests/conftest.py

### 100. `account_database()`

[查看函数源码](../tests/conftest.py#L20)

**当前函数的功能：** 调用 create_user 建立一次账号模板；每项测试复制文件，避免重复密码派生的开销。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tmp_path_factory.mktemp()` | 让 pytest 为账号模板创建会话级临时目录。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `auth.create_user()` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |

**装饰器：**

- `pytest.fixture`：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。

### 101. `app_db()`

[查看函数源码](../tests/conftest.py#L47)

**当前函数的功能：** 复制模板到测试临时目录，不复制任何用户凭据或实际工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `shutil.copyfile()` | 把测试账号模板复制到当前测试独有的数据库文件，避免修改共享或真实数据。 |

**装饰器：**

- `pytest.fixture`：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。

### 102. `ctx()`

[查看函数源码](../tests/conftest.py#L62)

**当前函数的功能：** 调用 create_thread 创建客户会话，再由应用构造 Context。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `sessions.create_thread()` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |

**装饰器：**

- `pytest.fixture`：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。

### 103. `new_request()`

[查看函数源码](../tests/conftest.py#L77)

**当前函数的功能：** 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `sessions.active_request()` | 查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。 |
| `sessions.abandon_request()` | 撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。 |
| `sessions.begin_request()` | 在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。 |

## tests/test_actions.py

### 104. `proposal()`

[查看函数源码](../tests/test_actions.py#L19)

**当前函数的功能：** 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `new_request()` | 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |

### 105. `created()`

[查看函数源码](../tests/test_actions.py#L34)

**当前函数的功能：** 通过提案加显式确认建立测试工单，不绕过执行层。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |

### 106. `other_context()`

[查看函数源码](../tests/test_actions.py#L45)

**当前函数的功能：** 为另一已有测试账号创建独立会话。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `sessions.create_thread()` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `Context()` | 创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。 |

### 107. `test_atomic_migration_preserves_legacy_rows()`

[查看函数源码](../tests/test_actions.py#L63)

**当前函数的功能：** 建立旧版单表数据库，验证自动迁移保留原工单、设置 legacy 归属，并让新编号接着旧编号递增。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `sqlite3.connect()` | 打开指定 SQLite 文件连接；迁移测试也用它建立原始旧表，绕开应用迁移逻辑。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 108. `test_same_confirmation_concurrent_creates_once()`

[查看函数源码](../tests/test_actions.py#L98)

**当前函数的功能：** 并发确认同一个 operation_id 十二次，验证只新建一张工单、一条创建审计，其余调用复用结果。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `concurrent.futures.ThreadPoolExecutor()` | 建立有界线程池，模拟多个调用同时访问同一个数据库或确认操作。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `range()` | 产生整数序列，供有界重试、模拟轮次或并发任务循环使用。 |
| `pool.map()` | 把输入逐个交给指定函数并在线程池中执行，按输入顺序收集结果。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `all()` | 检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。 |
| `result.get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `actions.read_ticket()` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |

**匿名函数：**

- `lambda _: actions.confirm_action(ctx, pending['operation_id'])`：由线程池调用；忽略输入序号，让每个任务确认同一个操作以验证幂等和事务。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 109. `test_confirmation_expiry_tampering_and_cancel()`

[查看函数源码](../tests/test_actions.py#L133)

**当前函数的功能：** 分别模拟确认过期、冻结参数被篡改和用户撤销，验证后续确认被拒绝，工单表保持为空。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `json.dumps()` | 把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

**装饰器：**

- `pytest.mark.parametrize`：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 110. `test_cross_user_and_cross_thread_confirmation()`

[查看函数源码](../tests/test_actions.py#L158)

**当前函数的功能：** 尝试用其他客户或同一客户的另一会话确认卡片，验证用户与会话绑定不能被绕过。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `other_context()` | 为另一已有测试账号创建独立会话。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 111. `test_new_message_invalidates_old_confirmation()`

[查看函数源码](../tests/test_actions.py#L177)

**当前函数的功能：** 先提出建单，再发送修改型号的新消息，验证旧确认卡片失效。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `new_request()` | 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 112. `test_changed_retry_conflicts()`

[查看函数源码](../tests/test_actions.py#L193)

**当前函数的功能：** 同一请求改成另一型号重试时应返回冲突；再确认原卡片，仍按原型号创建。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `actions.propose()` | 只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 113. `test_customer_cannot_see_other_customer_data()`

[查看函数源码](../tests/test_actions.py#L215)

**当前函数的功能：** 创建属于 alice 的工单后改用 bob 查询，验证编号查询、全量筛选和会话读取都不泄露他人数据。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `other_context()` | 为另一已有测试账号创建独立会话。 |
| `actions.read_ticket()` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |
| `actions.search_tickets()` | 按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。 |
| `pytest.raises()` | 声明代码块应抛出指定异常；未抛出或异常类型不对都会使测试失败。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 114. `test_assignment_priority_and_duplicate_detection()`

[查看函数源码](../tests/test_actions.py#L231)

**当前函数的功能：** 验证按专长自动分派、同型号同故障相似单提示、重复建单额外确认，以及安全故障的紧急优先级。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 115. `test_new_duplicate_during_confirmation_requires_new_proposal()`

[查看函数源码](../tests/test_actions.py#L257)

**当前函数的功能：** 在卡片生成后由另一会话创建相似工单，验证原卡片即使勾选重复确认也必须重新发起核对。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `other_context()` | 为另一已有测试账号创建独立会话。 |
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 116. `test_full_lifecycle_and_audit()`

[查看函数源码](../tests/test_actions.py#L279)

**当前函数的功能：** 轮换维修人员与客户身份走完五阶段生命周期，验证每次确认后的状态，以及五条审计的实际操作人。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `other_context()` | 为另一已有测试账号创建独立会话。 |
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `actions.read_ticket()` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 117. `test_customer_cannot_start_or_skip_repair()`

[查看函数源码](../tests/test_actions.py#L319)

**当前函数的功能：** 对多种目标状态参数化测试，验证客户不能从待处理直接开始、完成或跳过维修，也不能设置未知状态。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `storage.get_ticket_status()` | 可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。 |

**装饰器：**

- `pytest.mark.parametrize`：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 118. `test_stale_version_and_role_recheck()`

[查看函数源码](../tests/test_actions.py#L345)

**当前函数的功能：** 分别在卡片生成后修改工单版本、降低维修账号权限，验证确认时会重新检查版本和角色。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `other_context()` | 为另一已有测试账号创建独立会话。 |
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 119. `test_supplement_handoff_priority_assignment_cancel()`

[查看函数源码](../tests/test_actions.py#L387)

**当前函数的功能：** 通过真实确认入口依次补充信息、申请人工、调整优先级、分派和取消，核对持久字段及取消后的状态限制。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `other_context()` | 为另一已有测试账号创建独立会话。 |
| `actions.read_ticket()` | 调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 120. `test_search_filters()`

[查看函数源码](../tests/test_actions.py#L430)

**当前函数的功能：** 检查型号、编号、状态和日期过滤，并验证无效日期及逆序日期范围返回错误。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `actions.search_tickets()` | 按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 121. `test_registration_cannot_self_promote()`

[查看函数源码](../tests/test_actions.py#L459)

**当前函数的功能：** 验证普通注册不能创建管理员，首次初始化不能重复使用，以及登录令牌在退出后失效。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `auth.create_user()` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `auth.login()` | 调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。 |
| `auth.authenticate()` | 调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。 |
| `auth.logout()` | 调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 122. `test_legacy_other_issue_is_detected_as_duplicate()`

[查看函数源码](../tests/test_actions.py#L486)

**当前函数的功能：** 把已有工单类别改成旧版 other，验证从原始描述补判故障类别后仍能识别相似工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `created()` | 通过提案加显式确认建立测试工单，不绕过执行层。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `db.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `proposal()` | 为测试创建真实请求并调用 propose；每次提案均需独立应用请求。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

## tests/test_app.py

### 123. `page()`

[查看函数源码](../tests/test_app.py#L24)

**当前函数的功能：** 配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `monkeypatch.setenv()` | 在测试期间临时设置环境变量，例如数据库路径与模拟密钥；测试结束自动还原。 |
| `importlib.import_module()` | 按模块名导入模块；评测/测试用来替换模型加载入口，不加载用户输入的任意模块。 |
| `monkeypatch.setattr()` | 在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。 |
| `auth.login()` | 调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `AppTest.from_file()` | 从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。 |
| `app.run()` | 执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。 |

**匿名函数：**

- `lambda _: model`：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。

### 124. `test_page_without_credentials()`

[查看函数源码](../tests/test_app.py#L47)

**当前函数的功能：** 模拟缺少模型密钥，验证聊天输入禁用，但已登录用户仍能打开没有工单的工作台。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `page()` | 配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 125. `test_page_requires_login()`

[查看函数源码](../tests/test_app.py#L62)

**当前函数的功能：** 不提供登录令牌启动页面，验证只显示账号登录输入，不显示售后聊天。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `monkeypatch.setenv()` | 在测试期间临时设置环境变量，例如数据库路径与模拟密钥；测试结束自动还原。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `AppTest.from_file()` | 从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。 |
| `AppTest.from_file(...).run()` | 执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 126. `test_confirmation_card_restores_after_refresh()`

[查看函数源码](../tests/test_app.py#L101)

**当前函数的功能：** 用脚本模型提出建单，在新的页面实例中恢复相同登录与会话，点击确认后检查只创建一张工单且卡片消失。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `ScriptedModel()` | 构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。 |
| `page()` | 配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。 |
| `app.chat_input[0].set_value()` | 设置测试页面控件的值；后续 run 才触发完整页面处理。 |
| `app.chat_input[0].set_value(...).run()` | 执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `sessions.list_threads()` | 参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `AppTest.from_file()` | 从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。 |
| `refreshed.query_params.update()` | 合并字典或测试页面 URL 参数，用相同登录令牌和 thread_id 模拟刷新。 |
| `refreshed.run()` | 执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。 |
| `next()` | 取迭代器的下一项；脚本模型用它取响应，页面测试用它定位匹配按钮。 |
| `next(...).click()` | 在 AppTest 中记录一次模拟点击；随后 run 执行按钮对应的 Python 分支。 |
| `next(...).click(...).run()` | 执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 127. `test_ui_no_applicable_faq()`

[查看函数源码](../tests/test_app.py#L145)

**当前函数的功能：** 让模型尝试给 X100 蓝牙问题套用资料，验证页面明确显示无适用资料并保持工单表为空。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `ScriptedModel()` | 构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。 |
| `page()` | 配置隔离数据库，调用登录函数获得真实测试令牌后运行页面。 |
| `app.chat_input[0].set_value()` | 设置测试页面控件的值；后续 run 才触发完整页面处理。 |
| `app.chat_input[0].set_value(...).run()` | 执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 128. `test_staff_workbench_includes_customer_tickets()`

[查看函数源码](../tests/test_app.py#L171)

**当前函数的功能：** 先种入客户工单，再以管理员打开页面，验证工作人员能在详情选择框看到客户工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `storage.insert_ticket()` | 可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。 |
| `monkeypatch.setenv()` | 在测试期间临时设置环境变量，例如数据库路径与模拟密钥；测试结束自动还原。 |
| `auth.login()` | 调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `AppTest.from_file()` | 从 app.py 创建 Streamlit 测试页面对象，后续 run 才运行页面。 |
| `app.run()` | 执行或重跑 Streamlit AppTest 页面，让设置的输入和按钮动作生效。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

## tests/test_context.py

### 129. `test_explicit_facts()`

[查看函数源码](../tests/test_context.py#L34)

**当前函数的功能：** 对明确给出型号和故障的中文输入做参数化测试，核对结构化记忆里的 device_model 与 issue_type。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `sessions.extract_facts()` | 调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。 |

**装饰器：**

- `pytest.mark.parametrize`：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 130. `test_model_filter_and_synonyms()`

[查看函数源码](../tests/test_context.py#L44)

**当前函数的功能：** 核对型号隔离、蓝牙同义词、缺少型号、含糊故障和参数型号冲突，并确认来源字段可追溯。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `knowledge.search()` | 调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 131. `test_bm25_and_step_exclusion()`

[查看函数源码](../tests/test_context.py#L60)

**当前函数的功能：** 确认相关文档的 BM25 分数更高，并验证已尝试步骤不会再次出现在剩余步骤首位。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `knowledge.bm25()` | 调用 tokenize/Counter/log 计算 BM25；只在已经按型号过滤的资料中排序。 |
| `knowledge.search()` | 调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 132. `test_structure_memory_survives_process()`

[查看函数源码](../tests/test_context.py#L75)

**当前函数的功能：** 保存两轮明确事实后启动新的 Python 进程读取同一会话，验证型号和已重启记录不依赖进程内存。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `new_request()` | 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。 |
| `subprocess.check_output()` | 启动新的 Python 进程并读取标准输出，验证数据持久化与重试不依赖当前内存。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

传给子进程的 code 字符串另外调用 get_thread() 读取持久记忆，并用 json.dumps()/print() 返回 JSON；这些在新进程中执行。

### 133. `test_lease_blocks_concurrent_run()`

[查看函数源码](../tests/test_context.py#L96)

**当前函数的功能：** 获取请求租约后再次申请执行，验证同一请求不能并发执行，也不能在租约活动时被结束。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `new_request()` | 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。 |
| `sessions.claim_request()` | BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。 |
| `pytest.raises()` | 声明代码块应抛出指定异常；未抛出或异常类型不对都会使测试失败。 |
| `sessions.abandon_request()` | 撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 134. `test_trim_keeps_complete_tool_pairs()`

[查看函数源码](../tests/test_context.py#L118)

**当前函数的功能：** 构造十二轮用户、工具请求、工具结果和回复，验证历史裁剪保留完整工具配对并符合轮数限制。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `range()` | 产生整数序列，供有界重试、模拟轮次或并发任务循环使用。 |
| `HumanMessage()` | 构造用户消息；固定 id 可让检查点重试合并同一输入，避免重复追加。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `ToolMessage()` | 构造工具返回消息，通过 tool_call_id 对应模型上一条工具请求。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `messages.extend()` | 把另一序列的每个元素追加到列表，合并消息或分词结果。 |
| `trim_conversation()` | 按 HumanMessage 划分完整轮次再裁剪，不拆开 AI 工具调用与 ToolMessage 配对。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 135. `test_ten_turn_conversation_memory_summary_and_no_repeated_steps()`

[查看函数源码](../tests/test_context.py#L163)

**当前函数的功能：** 执行十轮真实图与脚本模型对话，检查设备事实、尝试步骤、排查耗尽、早期摘要及完整可见对话，并排除模型乱编文本。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `range()` | 产生整数序列，供有界重试、模拟轮次或并发任务循环使用。 |
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `responses.extend()` | 把另一序列的每个元素追加到列表，合并消息或分词结果。 |
| `ScriptedModel()` | 构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。 |
| `monkeypatch.setattr()` | 在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。 |
| `new_request()` | 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。 |
| `run_request()` | 验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。 |
| `asyncio.run()` | 在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。 |
| `answers.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `字符串.join()` | 以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。 |

**匿名函数：**

- `lambda _: model`：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 136. `test_model_cannot_fabricate_memory()`

[查看函数源码](../tests/test_context.py#L200)

**当前函数的功能：** 让模型提交用户从未说过的 X200 证据，验证记忆工具拒绝、当前 X100 不被覆盖且没有工单写入。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `sessions.timeline()` | 先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。 |
| `event['result'].get()` | 按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 137. `test_exhaustion_is_remembered_after_actual_step_feedback()`

[查看函数源码](../tests/test_context.py#L238)

**当前函数的功能：** 准备只剩最后一个可信步骤的会话，展示后接收明确失败反馈，验证耗尽状态持久保留，换型号时重置。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `sessions.TicketContext()` | 按 Pydantic 模型校验并补齐结构化工单记忆，列表默认值彼此独立。 |
| `sessions.TicketContext(...).model_dump()` | 把消息或 Pydantic 记忆对象转换为普通字典；mode=json 时转换为适合 JSON 的字段值。 |
| `knowledge.search()` | 调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。 |
| `render_faq()` | 用可信 FAQ 返回值选择一个新步骤并引用来源；调用方负责保存 last_suggested_step。 |
| `sessions.save_memory()` | 用 TicketContext 验证结构后 UPDATE；只允许修改当前用户的会话。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `sessions.get_thread()` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `sessions.extract_facts()` | 调用 model_in/classify_issue 提取明确事实；把用户反馈绑定到上一条真正展示的排查步骤。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 138. `test_checkpoint_keeps_only_trusted_final_text()`

[查看函数源码](../tests/test_context.py#L276)

**当前函数的功能：** 先让模型生成虚构退款文字，再发下一轮消息，检查模型看到的历史只包含应用实际展示的可信回复。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `getattr()` | 读取属性并允许指定缺省值，兼容字典之外的消息对象。 |
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `any()` | 检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

## tests/test_evaluation.py

### 139. `test_reject_fabricated_creation()`

[查看函数源码](../tests/test_evaluation.py#L18)

**当前函数的功能：** 验证评测器拒绝没有数据库记录和成功确认支持的“已创建成功”陈述。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `answer_consistent()` | 用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 140. `test_reject_wrong_status_even_if_database_did_not_change()`

[查看函数源码](../tests/test_evaluation.py#L27)

**当前函数的功能：** 保持数据库状态为待处理，验证声称已解决会失败，而正确的待处理陈述能够通过。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `answer_consistent()` | 用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 141. `test_unconfirmed_write_fails_evaluation()`

[查看函数源码](../tests/test_evaluation.py#L39)

**当前函数的功能：** 构造只有待确认提案却已出现工单行的结果，验证评测器能发现确认前非法写入。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `check_turn()` | 比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 142. `test_missing_required_tool_evidence_fails()`

[查看函数源码](../tests/test_evaluation.py#L62)

**当前函数的功能：** 答案看似合理但缺少预期 FAQ 工具证据时，评测必须失败。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `check_turn()` | 比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 143. `test_each_reply_is_compared_to_its_own_transaction_snapshot()`

[查看函数源码](../tests/test_evaluation.py#L72)

**当前函数的功能：** 分别核对确认前的待处理陈述与确认后的已关闭陈述，再注入一个错误旧状态，验证时序比较不漏报也不误报。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `check_turn()` | 比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

## tests/test_graph.py

### 144. `ScriptedModel.__init__()`

[查看函数源码](../tests/test_graph.py#L24)

**当前函数的功能：** 调用 iter 保存预设序列。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `iter()` | 把固定响应列表转成迭代器，让脚本模型逐条返回消息。 |

### 145. `ScriptedModel.bind_tools()`

[查看函数源码](../tests/test_graph.py#L33)

**当前函数的功能：** 模拟工具绑定，不执行工具；返回自身。

本函数没有调用其他函数，仅比较已有字段、返回固定值或返回对象本身。

### 146. `ScriptedModel.ainvoke()`

[查看函数源码](../tests/test_graph.py#L43)

**当前函数的功能：** 记录模型输入，再 next 返回预设结果或抛出预设异常。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `self.inputs.append()` | 把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。 |
| `next()` | 取迭代器的下一项；脚本模型用它取响应，页面测试用它定位匹配按钮。 |
| `isinstance()` | 判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。 |

### 147. `tool_call()`

[查看函数源码](../tests/test_graph.py#L56)

**当前函数的功能：** 构造 AIMessage 工具请求，由真实执行器校验并执行。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |

### 148. `run_script()`

[查看函数源码](../tests/test_graph.py#L73)

**当前函数的功能：** 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `ScriptedModel()` | 构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。 |
| `monkeypatch.setattr()` | 在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。 |
| `new_request()` | 结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。 |
| `run_request()` | 验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。 |
| `asyncio.run()` | 在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。 |

**匿名函数：**

- `lambda _: model`：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。

### 149. `test_identity_and_confirmation_are_not_model_parameters()`

[查看函数源码](../tests/test_graph.py#L93)

**当前函数的功能：** 把所有模型工具转成真实 schema，确认没有确认执行工具，也没有角色、用户、请求号或 confirmed 等可信应用字段。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `convert_to_openai_tool()` | 把 Python 工具转换成模型可见的工具 schema，测试据此检查是否泄露可信参数。 |
| `schemas.values()` | 遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。 |
| `set()` | 构造不重复元素集合，用于检查未知参数、工具配对或唯一查询词。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 150. `test_proposal_never_writes_until_click_and_model_receives_result()`

[查看函数源码](../tests/test_graph.py#L123)

**当前函数的功能：** 让脚本模型提出建单并谎称成功，验证工具结果已交回模型、页面显示尚未执行、数据库在显式确认前为空。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `actions.confirm_action()` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 151. `test_prohibited_operation_denied_even_if_model_calls_tool()`

[查看函数源码](../tests/test_graph.py#L154)

**当前函数的功能：** 用户明确禁止建单时仍让脚本模型请求建单，验证执行层拒绝提案和写入。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 152. `test_model_cannot_supply_confirmed_or_call_confirmation()`

[查看函数源码](../tests/test_graph.py#L182)

**当前函数的功能：** 模拟额外 confirmed 参数及不存在的 confirm_action 模型工具，验证两种绕过确认的方式都无效。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 153. `test_no_tool_fabricated_status_is_not_displayed()`

[查看函数源码](../tests/test_graph.py#L218)

**当前函数的功能：** 模型未取得工具证据却声称已解决和退款，验证应用最终回复不会展示这些未经验证的陈述。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 154. `test_faq_wrong_model_cannot_bypass_filter()`

[查看函数源码](../tests/test_graph.py#L236)

**当前函数的功能：** 用户已明确 X100 时让模型检索 X200，验证型号冲突被工具层拒绝，错误教程不会显示。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 155. `test_tool_budget_stops_before_extra_execution()`

[查看函数源码](../tests/test_graph.py#L261)

**当前函数的功能：** 让模型一次请求五次建单、只允许一次工具执行，验证只保存一个提案并且没有实际工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |
| `range()` | 产生整数序列，供有界重试、模拟轮次或并发任务循环使用。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 156. `test_token_budget_prevents_model_call()`

[查看函数源码](../tests/test_graph.py#L285)

**当前函数的功能：** 把 token 预算设为 1，验证预检在调用模型前终止，也不产生待确认操作。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 157. `test_sqlite_checkpoint_resume_does_not_repeat_tool()`

[查看函数源码](../tests/test_graph.py#L309)

**当前函数的功能：** 在提案成功后的模型阶段注入异常，再重试原请求，验证从检查点继续、工具不重复执行、请求最终完成。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `RuntimeError()` | 构造执行/协议异常；测试中也用于模拟中断，不是业务成功结果。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `actions.pending_actions()` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `ScriptedModel()` | 构造记录输入、逐条返回响应或异常的测试模型，用它精确制造成功、超时和越权场景。 |
| `monkeypatch.setattr()` | 在测试期间把模型加载函数替换为脚本模型；真实图、工具和数据库仍会执行。 |
| `run_request()` | 验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。 |
| `asyncio.run()` | 在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。 |
| `sessions.get_request()` | 按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。 |

**匿名函数：**

- `lambda _: model`：仅在测试中替代模型加载器；忽略模型名称，返回当前准备好的 ScriptedModel。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 158. `test_transient_model_timeout_retried_with_accounted_budget()`

[查看函数源码](../tests/test_graph.py#L345)

**当前函数的功能：** 先注入一次模型超时再返回有效提案，验证仅有界重试、累计模型调用和估算用量均保留，且不自动写工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `TimeoutError()` | 构造超时异常；此处测试用它模拟可重试的模型请求失败。 |
| `tool_call()` | 构造 AIMessage 工具请求，由真实执行器校验并执行。 |
| `AIMessage()` | 构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。 |
| `run_script()` | 替换模型后通过 service.run_request 运行真实检查点与请求生命周期。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

## tests/test_tickets.py

### 159. `db()`

[查看函数源码](../tests/test_tickets.py#L20)

**当前函数的功能：** 为每个需要数据库的测试提供独立的 SQLite 文件路径。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `str()` | 把路径、编号或异常等转换为文本，便于传参、显示或构造标识。 |

**装饰器：**

- `pytest.fixture`：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。

### 160. `test_create_and_query_real_record()`

[查看函数源码](../tests/test_tickets.py#L34)

**当前函数的功能：** 验证建单真正写入数据库、首尾空白被清理、返回字段与数据库一致，且编号规范化查询可用。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |
| `storage.connect()` | 作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。 |
| `connection.execute()` | 在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。 |
| `connection.execute(...).fetchone()` | 从 execute 返回的游标读取一行；没有匹配记录时返回 None，计数查询则返回一个统计行。 |
| `dict()` | 把数据库行或键值对转换成可按字段访问的普通字典。 |
| `storage.get_ticket_status()` | 可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 161. `test_missing_fields_do_not_write()`

[查看函数源码](../tests/test_tickets.py#L64)

**当前函数的功能：** 检查缺型号、缺描述和两者都缺失的情况，确保返回缺失字段且不写工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

**装饰器：**

- `pytest.mark.parametrize`：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 162. `test_invalid_input_does_not_write()`

[查看函数源码](../tests/test_tickets.py#L87)

**当前函数的功能：** 检查型号超长、描述超长和请求编号缺失时返回对应错误，并阻止写入。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

**装饰器：**

- `pytest.mark.parametrize`：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 163. `test_repeated_request_returns_original()`

[查看函数源码](../tests/test_tickets.py#L99)

**当前函数的功能：** 验证同一请求编号和同一组参数重复提交时，返回原记录并标记复用。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 164. `test_changed_retry_payload_is_a_conflict()`

[查看函数源码](../tests/test_tickets.py#L113)

**当前函数的功能：** 验证复用请求编号却改变业务参数时返回冲突，不覆盖原记录，也不新增工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 165. `test_concurrent_requests_are_atomic()`

[查看函数源码](../tests/test_tickets.py#L138)

**当前函数的功能：** 并发提交 16 次请求，分别检查相同编号只建一张、不同编号各建一张，验证事务和去重约束。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `concurrent.futures.ThreadPoolExecutor()` | 建立有界线程池，模拟多个调用同时访问同一个数据库或确认操作。 |
| `range()` | 产生整数序列，供有界重试、模拟轮次或并发任务循环使用。 |
| `pool.map()` | 把输入逐个交给指定函数并在线程池中执行，按输入顺序收集结果。 |
| `list()` | 把迭代器或集合展开成列表，或复制列表以便收集后续结果。 |
| `all()` | 检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |
| `sum()` | 累加数值；对布尔表达式累加时，True 按 1 计数。 |

**间接调用与回调：**

- `submit`：由 pool.map 调用/注册：在线程池中执行一次建单，根据外层测试模式使用同一个编号或各自不同的编号。

**装饰器：**

- `pytest.mark.parametrize`：为多组输入分别执行测试函数；它发生在测试注册/收集阶段，不是业务函数内部调用。

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 166. `test_concurrent_requests_are_atomic.submit()`

[查看函数源码](../tests/test_tickets.py#L143)

**当前函数的功能：** 在线程池中执行一次建单，根据外层测试模式使用同一个编号或各自不同的编号。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |

### 167. `test_query_missing_and_invalid_ids()`

[查看函数源码](../tests/test_tickets.py#L163)

**当前函数的功能：** 检查格式正确但不存在的编号，以及包含 SQL 片段的非法编号，都返回明确错误而不生成工单。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.get_ticket_status()` | 可信内部查询；调用 normalize_id/connect，返回数据库事实。外部入口另做身份校验。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

### 168. `test_survives_new_process_and_retry()`

[查看函数源码](../tests/test_tickets.py#L182)

**当前函数的功能：** 创建记录后启动新的 Python 进程重试同一请求，验证数据和请求去重不依赖当前进程内存。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `storage.create_ticket()` | 兼容旧版的可信内部入口，仅供迁移/测试；模型工具不调用它。调用校验和 insert_ticket。 |
| `subprocess.check_output()` | 启动新的 Python 进程并读取标准输出，验证数据持久化与重试不依赖当前内存。 |
| `json.loads()` | 把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。 |
| `storage.list_tickets()` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `len()` | 取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

子进程 code 字符串调用 storage.create_ticket() 重试同一请求，json.dumps()/print() 输出结果；这不是在父进程里再次执行。

### 169. `test_faq_keyword_search()`

[查看函数源码](../tests/test_tickets.py#L200)

**当前函数的功能：** 验证中文、英文网络词和蓝牙检索命中正确 FAQ；X100 蓝牙、无资料故障和空查询均不能返回不适用资料。

| 内部调用 | 做什么 / 为什么用 |
|---|---|
| `search_faq()` | 调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。 |

测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。

## 没有手写具名函数的文件与自动生成方法

| 位置 | 作用与内部调用 |
|---|---|
| `context.py / Context` | `@dataclass(kw_only=True)` 自动生成关键字参数构造方法；`field(default_factory=lambda: os.getenv(...))` 每次创建 Context 才读取 MODEL。lambda 调用 `os.getenv` 从应用环境取得模型名，不能让模型决定身份。 |
| `state.py / InputState` | `field(default_factory=list)` 每次创建独立消息列表；`Annotated[..., add_messages]` 登记消息合并器，LangGraph 按消息 ID 添加或替换消息。 |
| `state.py / State` | `field(default_factory=lambda: TicketContext().model_dump())` 每次构造独立业务事实字典；其他 list 默认工厂同样避免共享列表。 |
| `sessions.py / TicketContext` | Pydantic 的 BaseModel 负责自动构造、校验和 `model_dump`；`Field(default_factory=list)` 为每个会话建立自己的尝试步骤列表。 |
| `prompts.py` | 保存 SYSTEM_PROMPT 文本，没有自定义函数；由 call_model 用 format 填入时间，再附加可信上下文。 |
| `__init__.py` | 导入并公开已编译的 graph，没有手写函数；导入装配图不会发起模型推理。 |
| `graph.py` 顶层 | `StructuredTool.from_function` 为每个 TOOLS 函数提取 schema，建立 TOOL_MAP；`build_graph()` 编译默认图。 |
| `app.py` 顶层 | `load_dotenv` 载入配置，`st.set_page_config` 设置页面，`st.markdown` 加载样式，最后 `main()` 显示页面；交互重跑不会清空 SQLite。 |

## 三个常见误解

1. `tools.create_ticket()` 只提出操作；`actions.confirm_action()` 才是页面确认执行入口；`storage.create_ticket()` 是未暴露给模型的内部兼容函数。
2. `model.bind_tools()` 只是把工具 schema 告诉模型；`model.ainvoke()` 才请求模型，而真实工具函数由 `execute_tools()` 执行。
3. `builder.add_node()` 注册函数，`asyncio.to_thread()` 把函数交给线程，`pytest.fixture` 交给测试框架；它们与直接调用函数的时机不同。
