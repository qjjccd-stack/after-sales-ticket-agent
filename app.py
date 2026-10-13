"""本机售后工作台：登录、持久会话、确认卡片、执行时间线、工单全生命周期。"""

import asyncio
import json
import os

import streamlit as st
from dotenv import load_dotenv

from react_agent import actions, auth, knowledge, service, sessions, storage
from react_agent.context import Context

# 页面入口：load_dotenv() 读取配置，set_page_config() 设置标题/布局，markdown() 加载样式。
# 文件末尾调用 main() 显示登录或工作台；Streamlit 重跑页面时，会话和工单从 SQLite 恢复。
load_dotenv(storage.ROOT / ".env")
st.set_page_config(page_title="售后工单助手", page_icon="🛠️", layout="wide")
st.markdown(
    """<style>
.block-container {max-width:1500px;padding-top:2rem;}
[data-testid="stMetric"] {border:1px solid #dce3ed;border-radius:14px;padding:12px;min-height:110px;}
[data-testid="stMetricLabel"] p {white-space:normal;overflow:visible;text-overflow:clip;font-size:.85rem;}
[data-testid="stMetricLabel"] {min-height:2.7em;}
[data-testid="stMetricValue"] {font-size:clamp(1.2rem,1.8vw,1.6rem);}
[data-testid="stChatMessage"] {border-radius:14px;}
</style>""",
    unsafe_allow_html=True,
)
ROLE_LABELS = {
    "customer": "客户",
    "technician": "维修人员",
    "support": "人工客服",
    "admin": "管理员",
}


# 函数说明：show_login
# 功能：显示首次管理员设置或登录/客户注册；调用 auth，角色不由聊天内容或 URL 指定。
# 内部调用：
#   - st.title()：显示页面一级标题。
#   - st.caption()：显示辅助说明，例如 UTC 时间、模型配置或统计口径。
#   - auth.users()：供可信工作台列举人员；调用 connect/public_user 去除认证资料。
#   - st.radio()：显示单选项，用于切换登录与客户注册。
#   - st.info()：显示普通提示，例如等待确认、无密钥或操作结果。
#   - st.form()：创建表单容器，将一组输入汇集到一次提交。
#   - st.text_input()：显示单行文本框并返回输入；type=password 时隐藏密码。
#   - st.form_submit_button()：绘制表单提交按钮，返回本轮是否发生提交。
#   - auth.create_user()：事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。
#   - st.error()：显示校验失败或权限错误原因。
#   - auth.login()：调用 password_digest/compare_digest 校验，再生成 12 小时随机会话令牌；数据库仅存令牌散列。
#   - st.rerun()：立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。
def show_login():
    """显示首次管理员设置或登录/客户注册；调用 auth，角色不由聊天内容或 URL 指定。"""
    st.title("🛠️ 售后工单助手")
    st.caption("从故障排查到维修确认，让每一步都有记录。")
    initial = not auth.users()
    mode = (
        "首次设置"
        if initial
        else st.radio("进入工作台", ["登录", "注册客户账号"], horizontal=True)
    )
    if initial:
        st.info(
            "首次运行：创建本机管理员账号，之后可以在账号管理中添加维修人员和客服。"
        )
    with st.form("login_form"):
        username = st.text_input("账号", placeholder="例如 alice，至少 3 位")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button(
            "创建管理员并登录" if initial else mode, type="primary"
        )
    if submitted:
        if mode != "登录":
            registered = auth.create_user(
                username,
                password,
                "admin" if initial else "customer",
                bootstrap=initial,
            )
            if not registered["success"]:
                st.error(registered["message"])
                return
        outcome = auth.login(username, password)
        if outcome["success"]:
            st.session_state["auth_token"] = outcome["token"]
            st.rerun()
        else:
            st.error(outcome["message"])
    st.caption(
        "本机调试入口：重新打开页面可能需要登录，已有对话仍会保存。持久网页登录请使用新的服务页面。"
    )


# 函数说明：app_context
# 功能：创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。
# 内部调用：
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
def app_context(user, thread_id, request_id=""):
    """创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。"""
    return Context(user_id=user["user_id"], thread_id=thread_id, request_id=request_id)


# 函数说明：submit_form_action
# 功能：工作台表单生成独立请求，调用 propose 保存确认卡片；不直接修改工单。
# 内部调用：
#   - labels.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - 字典字面量.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - payload.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - sessions.begin_request()：在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。
#   - sessions.claim_request()：BEGIN IMMEDIATE 获取单请求执行租约；并行页面不能同时运行同一请求。
#   - app_context()：创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。
#   - actions.propose()：只保存待确认操作；调用参数校验、权限校验、相似检测，冻结参数摘要、版本和 15 分钟有效期。
#   - storage.log_execution()：调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。
#   - actions.render_result()：完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。
#   - sessions.finish_request()：校验租约后原子保存结果和助手消息；摘要从已保存旧消息中提取，原始记录仍完整保留。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - st.rerun()：立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。
def submit_form_action(context, action, payload):
    """工作台表单生成独立请求，调用 propose 保存确认卡片；不直接修改工单。"""
    try:
        labels = {
            "product_model": "设备型号",
            "issue_description": "故障描述",
            "impact": "影响范围",
            "ticket_id": "工单编号",
            "new_status": "新状态",
            "note": "说明",
            "description": "补充描述",
            "contact": "联系方式",
            "device_info": "设备信息",
            "assignee_id": "维修人员",
            "priority": "优先级",
        }
        text = (
            actions.ACTION_LABELS[action]
            + "："
            + "；".join(
                f"{labels.get(key, key)}：{ {'single': '单台设备', 'multiple': '多台设备', 'all': '全部设备'}.get(value, value) if key == 'impact' else value }"
                for key, value in payload.items()
                if value
            )
        )
        request_id = sessions.begin_request(context.thread_id, context.user_id, text)
        token = sessions.claim_request(request_id, context.user_id)
        current = app_context(
            {"user_id": context.user_id}, context.thread_id, request_id
        )
        outcome = actions.propose(current, action, payload)
        storage.log_execution(current, "tool", action, payload, outcome)
        sessions.finish_request(
            request_id,
            context.user_id,
            token,
            {"success": True, "answer": actions.render_result(outcome)},
        )
        st.session_state.notice = actions.render_result(outcome)
    except (ValueError, PermissionError) as error:
        st.session_state.notice = str(error)
    st.rerun()


# 函数说明：show_confirmations
# 功能：展示服务器保存的冻结参数；按钮只提交 operation_id，调用 confirm_action 验证并执行。
# 内部调用：
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
#   - st.container()：建立分组容器，border=True 时把待确认操作围成独立卡片。
#   - st.subheader()：显示当前区域的小标题。
#   - st.caption()：显示辅助说明，例如 UTC 时间、模型配置或统计口径。
#   - display.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - 字典字面量.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - st.write()：显示文本或字段值，支持简单 Markdown。
#   - payload.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - st.warning()：显示需要关注的提示，例如相似工单或未完成请求。
#   - st.dataframe()：显示可交互表格，用于相似工单、工单列表或人员名单。
#   - st.checkbox()：显示勾选项；此处要求用户明确接受重复建单。
#   - st.columns()：创建并列布局容器，后续可在各列绘制表单、按钮或指标。
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - left.button()：绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。
#   - right.button()：绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - actions.render_result()：完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。
#   - st.rerun()：立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。
def show_confirmations(context, key_prefix="chat"):
    """展示服务器保存的冻结参数；按钮只提交 operation_id，调用 confirm_action 验证并执行。"""
    for operation in actions.pending_actions(context):
        operation_id, payload = operation["operation_id"], operation["payload"]
        with st.container(border=True):
            st.subheader("待确认 · " + actions.ACTION_LABELS[operation["action"]])
            st.caption(
                "尚未修改工单。请核对本次操作，15 分钟内有效。发送新消息会撤销此卡片。"
            )
            display = {
                "product_model": "设备型号",
                "issue_description": "故障描述",
                "ticket_id": "工单编号",
                "new_status": "新状态",
                "previous_status": "当前状态",
                "description": "补充描述",
                "contact": "联系方式",
                "device_info": "设备信息",
                "priority": "优先级",
                "assigned_to": "自动分派",
                "assignee_id": "维修人员",
                "note": "说明",
                "impact": "影响范围",
            }
            for field, label in display.items():
                if field in payload:
                    value = payload[field] or "待分派"
                    if field == "impact":
                        value = {
                            "single": "单台设备",
                            "multiple": "多台设备",
                            "all": "全部设备",
                        }.get(value, value)
                    st.write(f"**{label}：** {value}")
            duplicates = payload.get("duplicates", [])
            accepted = False
            if duplicates:
                st.warning("发现未关闭的相似工单，建议先查看原记录。")
                st.dataframe(duplicates, hide_index=True, use_container_width=True)
                accepted = st.checkbox(
                    "已核对相似工单，仍需要新建",
                    key=f"{key_prefix}-duplicate-{operation_id}",
                )
            left, right = st.columns(2)
            confirm = left.button(
                "确认" + actions.ACTION_LABELS[operation["action"]],
                key=f"{key_prefix}-confirm-{operation_id}",
                type="primary",
                disabled=bool(duplicates) and not accepted,
            )
            cancel = right.button(
                "撤销本次操作", key=f"{key_prefix}-cancel-{operation_id}"
            )
            if confirm or cancel:
                outcome = actions.confirm_action(
                    context, operation_id, accept_duplicate=accepted, cancel=cancel
                )
                st.session_state.notice = actions.render_result(outcome)
                st.rerun()


# 函数说明：show_timeline
# 功能：读取真实 execution_events；只展示实际提取事实/工具/确认结果，不伪造模型思考过程。
# 内部调用：
#   - st.subheader()：显示当前区域的小标题。
#   - sessions.timeline()：先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。
#   - st.caption()：显示辅助说明，例如 UTC 时间、模型配置或统计口径。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - max()：选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。
#   - enumerate()：遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。
#   - 字典字面量.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - event['result'].get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - st.expander()：创建可展开/折叠的详情区域，容纳事实、日志或处理表单。
#   - st.json()：把真实参数或结果格式化为 JSON 详情供展开查看，不作为模型思考过程。
#   - service.usage_for()：从持久日志统计调用/工具/token/耗时；没有响应的模型请求按预留预算计入。
def show_timeline(context):
    """读取真实 execution_events；只展示实际提取事实/工具/确认结果，不伪造模型思考过程。"""
    st.subheader("执行时间线")
    events = sessions.timeline(context.thread_id, context.user_id)
    visible = [
        event
        for event in events
        if event["kind"] in {"tool", "confirmation", "answer", "facts"}
    ]
    if not visible:
        st.caption("发送消息后，这里会显示实际检索、工具结果和确认记录。")
    for index, event in enumerate(visible[-16:], max(1, len(visible) - 15)):
        label = {
            "confirmation": "用户确认并执行",
            "answer": "生成可信回复",
            "facts": "记录业务事实",
        }.get(event["kind"], event["name"])
        if event["result"].get("state") == "awaiting_confirmation":
            label += " · 等待确认"
        elif event["result"].get("success") is False:
            label += " · 未完成"
        with st.expander(
            f"{index:02d}  {label}", expanded=event["kind"] == "confirmation"
        ):
            st.caption(event["created_at"] + " · UTC")
            if event["args"]:
                st.json(event["args"])
            st.json(event["result"])
    usage = service.usage_for(events)
    st.caption(
        f"累计模型调用 {usage['model_calls']} 次 · 工具 {usage['tool_calls']} 次 · Token {usage['total_tokens']:,}"
        + ("（含估算）" if usage["estimated_tokens"] else "")
    )


# 函数说明：show_chat
# 功能：调用 begin_request/run_request 执行对话；页面刷新后从 SQLite 恢复记录、待确认和失败重试。
# 内部调用：
#   - st.columns()：创建并列布局容器，后续可在各列绘制表单、按钮或指标。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - st.subheader()：显示当前区域的小标题。
#   - st.info()：显示普通提示，例如等待确认、无密钥或操作结果。
#   - st.chat_message()：创建用户或助手消息气泡，再向其中渲染持久化的文本。
#   - st.markdown()：渲染已保存的聊天文本或页面 Markdown 内容。
#   - sessions.active_request()：查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。
#   - st.warning()：显示需要关注的提示，例如相似工单或未完成请求。
#   - first.button()：绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。
#   - second.button()：绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。
#   - sessions.abandon_request()：撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。
#   - st.rerun()：立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - st.chat_input()：取得用户本轮提交的聊天文本；禁用时不能发起模型请求。
#   - sessions.begin_request()：在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。
#   - sessions.get_request()：按 request_id 和 user_id 查询原始输入及结果，重试不重新生成业务编号。
#   - app_context()：创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。
#   - storage.log_execution()：调用 connect/INSERT 保存真实执行事件；不记录密钥、密码或模型私有推理。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - st.error()：显示校验失败或权限错误原因。
#   - st.spinner()：在耗时请求执行期间显示等待提示，退出代码块后移除。
#   - service.run_request()：验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。
#   - asyncio.run()：在同步入口中运行异步请求并等待结果；例如 Streamlit 页面和同步测试调用 Agent。
#   - show_confirmations()：展示服务器保存的冻结参数；按钮只提交 operation_id，调用 confirm_action 验证并执行。
#   - st.expander()：创建可展开/折叠的详情区域，容纳事实、日志或处理表单。
#   - st.write()：显示文本或字段值，支持简单 Markdown。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - show_timeline()：读取真实 execution_events；只展示实际提取事实/工具/确认结果，不伪造模型思考过程。
def show_chat(context, ready):
    """调用 begin_request/run_request 执行对话；页面刷新后从 SQLite 恢复记录、待确认和失败重试。"""
    chat, trace = st.columns([3, 2], gap="large")
    thread = sessions.get_thread(context.thread_id, context.user_id)
    with chat:
        st.subheader("售后对话")
        if not thread["transcript"]:
            st.info("告诉我设备型号和故障表现。申请建单或修改工单时，会先请你确认。")
        for item in thread["transcript"]:
            with st.chat_message(item["role"]):
                st.markdown(item["content"])
        active = sessions.active_request(context.thread_id, context.user_id)
        should_run = False
        if active:
            st.warning("这次请求尚未完成。重试将继续原请求和检查点。")
            first, second = st.columns(2)
            should_run = first.button("重试本次请求", disabled=not ready)
            if second.button("结束本次请求"):
                if sessions.abandon_request(active["request_id"], context.user_id):
                    st.rerun()
                st.info("请求仍在执行，请稍后刷新。")
        prompt = st.chat_input(
            "例如：我的 X100 无法联网", disabled=not ready or bool(active)
        )
        if prompt:
            try:
                request_id = sessions.begin_request(
                    context.thread_id, context.user_id, prompt
                )
                active = sessions.get_request(request_id, context.user_id)
                memory = sessions.get_thread(context.thread_id, context.user_id)[
                    "memory"
                ]
                storage.log_execution(
                    app_context(
                        {"user_id": context.user_id}, context.thread_id, request_id
                    ),
                    "facts",
                    "extract_facts",
                    {},
                    memory,
                )
                should_run = True
            except (ValueError, PermissionError) as error:
                st.error(str(error))
        if should_run:
            with st.spinner("正在检查资料和处理请求…"):
                try:
                    outcome = asyncio.run(
                        service.run_request(active["request_id"], context.user_id)
                    )
                    if not outcome["success"]:
                        st.session_state.notice = (
                            outcome["answer"] + "（" + outcome["error_code"] + "）"
                        )
                except (ValueError, PermissionError) as error:
                    st.session_state.notice = str(error)
            st.rerun()
        show_confirmations(context)
    with trace:
        memory = sessions.get_thread(context.thread_id, context.user_id)["memory"]
        with st.expander("当前设备与故障记录", expanded=True):
            st.write("设备：", memory["device_model"] or "尚未提供")
            st.write("故障：", memory["issue_description"] or "尚未提供")
            st.write("工单：", memory["ticket_id"] or "尚未创建")
            st.write("已尝试：", "、".join(memory["troubleshooting_steps"]) or "暂无")
        show_timeline(context)


# 函数说明：show_ticket_detail
# 功能：读取真实详情和事件，显示生命周期；各表单调用 submit_form_action 进入同一确认机制。
# 内部调用：
#   - actions.read_ticket()：调用 actor_in/normalize_id/visible 查询授权工单；需要时附带不可变处理记录。
#   - st.error()：显示校验失败或权限错误原因。
#   - st.subheader()：显示当前区域的小标题。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - st.write()：显示文本或字段值，支持简单 Markdown。
#   - st.columns()：创建并列布局容器，后续可在各列绘制表单、按钮或指标。
#   - first.metric()：显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。
#   - second.metric()：显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。
#   - third.metric()：显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。
#   - st.info()：显示普通提示，例如等待确认、无密钥或操作结果。
#   - st.caption()：显示辅助说明，例如 UTC 时间、模型配置或统计口径。
#   - st.expander()：创建可展开/折叠的详情区域，容纳事实、日志或处理表单。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - actions.ACTION_LABELS.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - before.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - after.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - st.json()：把真实参数或结果格式化为 JSON 详情供展开查看，不作为模型思考过程。
#   - st.form()：创建表单容器，将一组输入汇集到一次提交。
#   - st.text_area()：显示多行文本框，适合填写故障描述。
#   - st.text_input()：显示单行文本框并返回输入；type=password 时隐藏密码。
#   - st.form_submit_button()：绘制表单提交按钮，返回本轮是否发生提交。
#   - submit_form_action()：工作台表单生成独立请求，调用 propose 保存确认卡片；不直接修改工单。
#   - sorted()：返回按默认次序或 key 规则排好的新列表，不原地修改原列表。
#   - st.selectbox()：显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。
#   - auth.users()：供可信工作台列举人员；调用 connect/public_user 去除认证资料。
def show_ticket_detail(context, ticket_id, user):
    """读取真实详情和事件，显示生命周期；各表单调用 submit_form_action 进入同一确认机制。"""
    outcome = actions.read_ticket(context, ticket_id, history=True)
    if not outcome["success"]:
        st.error(outcome["message"])
        return
    ticket = outcome["ticket"]
    st.subheader(f"{ticket_id} · {ticket['product_model']}")
    st.write(
        " → ".join(
            f"**● {status}**" if ticket["status"] == status else status
            for status in storage.STATUSES
        )
    )
    first, second, third = st.columns(3)
    first.metric("当前状态", ticket["status"])
    second.metric("优先级", ticket["priority"])
    third.metric("处理人", ticket["assigned_to"] or "待分派")
    st.write("故障描述：", ticket["issue_description"])
    st.write("联系方式：", ticket["contact"] or "未提供")
    st.write("设备信息：", ticket["device_info"] or "未提供")
    if ticket["manual"]:
        st.info("此工单已标记人工接管。")
    st.caption(
        f"创建：{ticket['created_at']} · UTC ｜ 更新：{ticket['updated_at'] or ticket['created_at']} · UTC"
    )
    with st.expander("处理记录", expanded=True):
        for event in outcome["history"]:
            after = json.loads(event["after_data"])
            before = json.loads(event["before_data"])
            st.write(
                f"{event['created_at']} · {event['operator_id']} · {actions.ACTION_LABELS.get(event['action'], event['action'])}"
            )
            st.caption(
                f"{before.get('status', '未创建')} → {after.get('status')}  {event['note']}"
            )
            with st.expander(f"变更详情 #{event['event_id']}"):
                st.json({"变更前": before, "变更后": after})
    if ticket["status"] == "已关闭":
        return
    with st.expander("补充工单信息"):
        with st.form(f"supplement-{ticket_id}"):
            description = st.text_area("补充故障描述")
            contact = st.text_input("联系方式")
            device_info = st.text_input("设备信息 / 序列号")
            if st.form_submit_button("预览补充信息"):
                submit_form_action(
                    context,
                    "supplement_ticket",
                    {
                        "ticket_id": ticket_id,
                        "description": description,
                        "contact": contact,
                        "device_info": device_info,
                    },
                )
    targets = sorted(actions.TRANSITIONS[ticket["status"]])
    if user["role"] == "customer":
        targets = [
            status for status in targets if ticket["status"] in {"待用户确认", "已解决"}
        ]
    if targets:
        with st.expander("处理 / 确认维修结果"):
            with st.form(f"status-{ticket_id}"):
                new_status = st.selectbox("下一状态", targets)
                note = st.text_input("处理说明", placeholder="例如：设备已经恢复正常")
                if st.form_submit_button("预览状态变更"):
                    submit_form_action(
                        context,
                        "update_ticket_status",
                        {
                            "ticket_id": ticket_id,
                            "new_status": new_status,
                            "note": note,
                        },
                    )
    with st.expander("取消 / 转人工"):
        with st.form(f"manual-{ticket_id}"):
            reason = st.text_input("原因", value="标准排查未能解决")
            if st.form_submit_button("申请人工接管"):
                submit_form_action(
                    context, "handoff_ticket", {"ticket_id": ticket_id, "note": reason}
                )
            if ticket["status"] == "待处理" and st.form_submit_button("申请取消工单"):
                submit_form_action(
                    context, "cancel_ticket", {"ticket_id": ticket_id, "note": reason}
                )
    if user["role"] in {"admin", "support"}:
        with st.expander("分派与优先级"):
            technicians = [
                person["user_id"]
                for person in auth.users()
                if person["role"] == "technician"
            ]
            with st.form(f"assign-{ticket_id}"):
                if technicians:
                    assignee = st.selectbox("分派给", technicians)
                    if st.form_submit_button("预览分派"):
                        submit_form_action(
                            context,
                            "assign_ticket",
                            {"ticket_id": ticket_id, "assignee_id": assignee},
                        )
                else:
                    st.caption("尚未添加维修人员，请管理员在账号管理中添加。")
                    st.form_submit_button("暂无可分派人员", disabled=True)
            with st.form(f"priority-{ticket_id}"):
                priority = st.selectbox("紧急程度", ["普通", "高", "紧急"])
                note = st.text_input("调整原因")
                if st.form_submit_button("预览优先级调整"):
                    submit_form_action(
                        context,
                        "set_ticket_priority",
                        {"ticket_id": ticket_id, "priority": priority, "note": note},
                    )


# 函数说明：show_workbench
# 功能：按权限筛选工单，提供详情、状态统计和可手工填写的建单表单，不依赖模型连通性。
# 内部调用：
#   - st.subheader()：显示当前区域的小标题。
#   - show_confirmations()：展示服务器保存的冻结参数；按钮只提交 operation_id，调用 confirm_action 验证并执行。
#   - st.expander()：创建可展开/折叠的详情区域，容纳事实、日志或处理表单。
#   - st.form()：创建表单容器，将一组输入汇集到一次提交。
#   - st.text_input()：显示单行文本框并返回输入；type=password 时隐藏密码。
#   - st.text_area()：显示多行文本框，适合填写故障描述。
#   - st.selectbox()：显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。
#   - st.form_submit_button()：绘制表单提交按钮，返回本轮是否发生提交。
#   - submit_form_action()：工作台表单生成独立请求，调用 propose 保存确认卡片；不直接修改工单。
#   - st.columns()：创建并列布局容器，后续可在各列绘制表单、按钮或指标。
#   - first.text_input()：显示单行文本框并返回输入；type=password 时隐藏密码。
#   - second.text_input()：显示单行文本框并返回输入；type=password 时隐藏密码。
#   - third.selectbox()：显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。
#   - actions.search_tickets()：按权限生成参数化 SQL，支持编号/型号/状态/日期筛选；最多返回 200 条。
#   - st.error()：显示校验失败或权限错误原因。
#   - outcome.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - zip()：把多个序列按位置配对，关联候选文档与分数或统计列与状态。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
#   - column.metric()：显示一项标签及数值，例如当前状态、优先级或某状态的工单数量。
#   - st.caption()：显示辅助说明，例如 UTC 时间、模型配置或统计口径。
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - st.dataframe()：显示可交互表格，用于相似工单、工单列表或人员名单。
#   - show_ticket_detail()：读取真实详情和事件，显示生命周期；各表单调用 submit_form_action 进入同一确认机制。
# 匿名函数：
#   - lambda value: {'single': '单台设备', 'multiple': '多台设备', 'all': '全部设备'}[value]：由 selectbox 的 format_func 调用，把影响范围内部值显示为中文；返回值只用于显示。
def show_workbench(context, user):
    """按权限筛选工单，提供详情、状态统计和可手工填写的建单表单，不依赖模型连通性。"""
    st.subheader("工单工作台" if user["role"] != "customer" else "我的售后工单")
    show_confirmations(context, key_prefix="workbench")
    with st.expander("填写新工单"):
        with st.form("manual_create"):
            model = st.text_input("设备型号")
            description = st.text_area("故障描述")
            impact = st.selectbox(
                "影响范围",
                ["single", "multiple", "all"],
                format_func=lambda value: {
                    "single": "单台设备",
                    "multiple": "多台设备",
                    "all": "全部设备",
                }[value],
            )
            if st.form_submit_button("预览建单信息"):
                submit_form_action(
                    context,
                    "create_ticket",
                    {
                        "product_model": model,
                        "issue_description": description,
                        "impact": impact,
                    },
                )
    first, second, third = st.columns(3)
    number = first.text_input("按工单编号查找")
    model_filter = second.text_input("按设备型号筛选")
    status_filter = third.selectbox("按状态筛选", ["全部", *storage.STATUSES])
    first, second = st.columns(2)
    start = first.text_input("创建起始日期", placeholder="YYYY-MM-DD（UTC）")
    end = second.text_input("创建结束日期", placeholder="YYYY-MM-DD（UTC）")
    outcome = actions.search_tickets(
        context,
        number,
        model_filter,
        "" if status_filter == "全部" else status_filter,
        start,
        end,
        mine=user["role"] == "customer",
    )
    if not outcome["success"]:
        st.error(outcome["message"])
    rows = outcome.get("tickets", [])
    metrics = st.columns(5)
    for column, status in zip(metrics, storage.STATUSES):
        column.metric(status, sum(row["status"] == status for row in rows))
    st.caption(
        "统计当前筛选结果；日期按 UTC。"
        + ("超过 200 条，请缩小筛选范围。" if outcome.get("truncated") else "")
    )
    if rows:
        table = [
            {
                "工单编号": row["ticket_id"],
                "设备": row["product_model"],
                "状态": row["status"],
                "优先级": row["priority"],
                "处理人": row["assigned_to"] or "待分派",
                "人工接管": bool(row["manual"]),
            }
            for row in rows
        ]
        st.dataframe(table, hide_index=True, use_container_width=True)
        selected = st.selectbox("查看工单详情", [row["ticket_id"] for row in rows])
        show_ticket_detail(context, selected, user)
    else:
        st.caption("暂无工单。")


# 函数说明：show_admin
# 功能：管理员创建真实工作人员与专长规则；调用 create_user 再次检查管理权限。
# 内部调用：
#   - st.subheader()：显示当前区域的小标题。
#   - auth.users()：供可信工作台列举人员；调用 connect/public_user 去除认证资料。
#   - st.dataframe()：显示可交互表格，用于相似工单、工单列表或人员名单。
#   - st.form()：创建表单容器，将一组输入汇集到一次提交。
#   - st.text_input()：显示单行文本框并返回输入；type=password 时隐藏密码。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
#   - st.selectbox()：显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。
#   - st.multiselect()：显示多选框，返回维修人员选择的故障专长列表。
#   - st.form_submit_button()：绘制表单提交按钮，返回本轮是否发生提交。
#   - item.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - item.strip(...).upper()：把字母转为大写，统一设备型号或错误码。
#   - models.split()：按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。
#   - auth.create_user()：事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。
#   - st.success()：显示成功或已配置状态提示。
#   - st.error()：显示校验失败或权限错误原因。
# 间接调用 / 回调：
#   - ROLE_LABELS.get：由 st.selectbox 调用/注册：按映射返回对应值；这里用于显示名称或评分选择，而不是立即主动调用。
def show_admin(user):
    """管理员创建真实工作人员与专长规则；调用 create_user 再次检查管理权限。"""
    st.subheader("账号与维修分派规则")
    st.dataframe(auth.users(), hide_index=True, use_container_width=True)
    with st.form("create_account"):
        name = st.text_input("新账号")
        password = st.text_input("初始密码", type="password")
        role = st.selectbox("账号角色", list(ROLE_LABELS), format_func=ROLE_LABELS.get)
        models = st.text_input("可处理型号", placeholder="X100,X200；留空表示不限")
        specialties = st.multiselect("故障专长", list(knowledge.SYNONYMS))
        if st.form_submit_button("创建账号"):
            outcome = auth.create_user(
                name,
                password,
                role,
                administrator=user["user_id"],
                models=[
                    item.strip().upper() for item in models.split(",") if item.strip()
                ],
                specialties=specialties,
            )
            if outcome["success"]:
                st.success("账号已创建。")
            else:
                st.error(outcome["message"])


# 函数说明：main
# 功能：恢复登录及选中会话，调用三个工作区；刷新不会清空 SQLite 中的对话和待确认卡片。
# 内部调用：
#   - st.query_params.get()：读取非敏感会话选择；旧 session 参数会清除，不作为身份依据。
#   - st.session_state.get()：读取仅保存在服务端 Streamlit 会话里的登录令牌。
#   - auth.authenticate()：调用 SHA256/SELECT 验证应用会话令牌及有效期；刷新后可恢复同一登录身份。
#   - show_login()：显示首次管理员设置或登录/客户注册；调用 auth，角色不由聊天内容或 URL 指定。
#   - sessions.list_threads()：参数化 SELECT 仅列出本人的会话，不包含他人的消息内容。
#   - sessions.create_thread()：验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。
#   - st.subheader()：显示当前区域的小标题。
#   - st.write()：显示文本或字段值，支持简单 Markdown。
#   - ids.index()：查找选中会话在可用编号列表中的位置，作为下拉框默认选择。
#   - st.selectbox()：显示单选下拉框，返回实际选中的值；format_func 只控制显示名称。
#   - st.button()：绘制按钮，返回本轮是否被点击；是否真正写入取决于后续确认入口。
#   - st.rerun()：立即重跑 Streamlit 页面，让界面反映最新数据库记录和提示；不是再次确认旧操作。
#   - st.caption()：显示辅助说明，例如 UTC 时间、模型配置或统计口径。
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
#   - model.startswith()：判断文本是否带指定前缀；此处按模型提供商选择需要读取的密钥。
#   - os.getenv()：读取环境变量，可指定默认值；读取的是当前进程配置。
#   - os.getenv(...).strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - st.success()：显示成功或已配置状态提示。
#   - st.info()：显示普通提示，例如等待确认、无密钥或操作结果。
#   - auth.logout()：调用 DELETE 撤销当前令牌；不会删除用户会话、工单或其他登录令牌。
#   - st.query_params.clear()：清空当前 URL 参数，退出登录后不再带旧令牌和选中的会话。
#   - app_context()：创建应用上下文；user 只能来自 auth.authenticate 的已验证身份。
#   - st.title()：显示页面一级标题。
#   - st.empty()：创建固定位置占位容器，后续显示一次性提示时尽量保持页面结构稳定。
#   - st.session_state.pop()：读取并移除一次性页面提示，避免每次重跑重复显示旧通知。
#   - notice_box.info()：显示普通提示，例如等待确认、无密钥或操作结果。
#   - st.tabs()：创建多个工作区标签及其容器；各标签的 Python 内容都会执行。
#   - show_chat()：调用 begin_request/run_request 执行对话；页面刷新后从 SQLite 恢复记录、待确认和失败重试。
#   - show_workbench()：按权限筛选工单，提供详情、状态统计和可手工填写的建单表单，不依赖模型连通性。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - show_admin()：管理员创建真实工作人员与专长规则；调用 create_user 再次检查管理权限。
# 间接调用 / 回调：
#   - labels.get：由 st.selectbox 调用/注册：按映射返回对应值；这里用于显示名称或评分选择，而不是立即主动调用。
def main():
    """恢复登录及选中会话，调用三个工作区；刷新不会清空 SQLite 中的对话和待确认卡片。"""
    # 不接受旧 URL 凭据；会话令牌只留在服务端 Streamlit 会话内。
    if "session" in st.query_params:
        del st.query_params["session"]
    token = st.session_state.get("auth_token", "")
    user = auth.authenticate(token)
    if not user:
        show_login()
        return
    threads = sessions.list_threads(user["user_id"])
    if not threads:
        sessions.create_thread(user["user_id"])
        threads = sessions.list_threads(user["user_id"])
    ids = [thread["thread_id"] for thread in threads]
    selected = st.query_params.get("thread", ids[0])
    if selected not in ids:
        selected = ids[0]
    labels = {thread["thread_id"]: thread["title"] for thread in threads}
    with st.sidebar:
        st.subheader("售后工作台")
        st.write(f"{user['user_id']} · {ROLE_LABELS[user['role']]}")
        chosen = st.selectbox(
            "历史会话", ids, index=ids.index(selected), format_func=labels.get
        )
        st.query_params["thread"] = chosen
        if st.button("新对话"):
            st.query_params["thread"] = sessions.create_thread(user["user_id"])
            st.rerun()
        st.caption("对话、故障记录和待确认操作已保存，刷新后可继续。")
        model = Context().model
        key = "DEEPSEEK_API_KEY" if model.startswith("deepseek/") else "OPENAI_API_KEY"
        ready = bool(os.getenv(key, "").strip())
        st.caption(f"模型：{model}")
        if ready:
            st.success("密钥已配置，连接待实际调用验证")
        else:
            st.info("尚未配置模型密钥；仍可通过工单工作台操作。")
        if st.button("退出登录"):
            auth.logout(token)
            st.session_state.pop("auth_token", None)
            st.query_params.clear()
            st.rerun()
    context = app_context(user, chosen)
    st.title("🛠️ 售后工单助手")
    st.caption("查清故障 · 确认操作 · 跟踪处理")
    notice_box = st.empty()
    if notice := st.session_state.pop("notice", None):
        notice_box.info(notice)
    names = ["售后对话", "工单工作台"] + (
        ["账号管理"] if user["role"] == "admin" else []
    )
    tabs = st.tabs(names)
    with tabs[0]:
        show_chat(context, ready)
    with tabs[1]:
        show_workbench(context, user)
    if len(tabs) > 2:
        with tabs[2]:
            show_admin(user)


main()
