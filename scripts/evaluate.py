"""业务契约评测：默认脚本模型；--mode live 才调用真实模型。分组、重复运行和业务证据都保留在隔离报告中。"""

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import re
import statistics
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage

from react_agent import actions, auth, sessions, storage
from react_agent.context import Context
from react_agent.evaluation import (
    assess_contract,
    classify_failures,
    confirmation_facts,
    grouped_metrics,
    validate_cases,
)
from react_agent.service import run_request


class OfflineModel:
    """可控的工具请求加伪造成功回答；检验真实执行层，不检验模型推理质量。"""

    # 函数说明：OfflineModel.__init__
    # 功能：根据场景定义构造响应队列；最终故意虚构状态以检验可信回复。
    # 内部调用：
    #   - enumerate()：遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。
    #   - AIMessage()：构造助手消息；content 保存文本，tool_calls 保存模型提出的工具请求，不会自行执行工具。
    #   - messages.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
    #   - iter()：把固定响应列表转成迭代器，让脚本模型逐条返回消息。
    def __init__(self, calls):
        """根据场景定义构造响应队列；最终故意虚构状态以检验可信回复。"""
        messages = []
        if calls:
            messages.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {**call, "id": f"call-{index}"}
                        for index, call in enumerate(calls)
                    ],
                )
            )
        messages.append(AIMessage(content="已经将T0001修改为已解决。"))
        self.messages = iter(messages)

    # 函数说明：OfflineModel.bind_tools
    # 功能：返回测试模型本身；真实工具仍由图执行器调用。
    # 内部调用：
    #   - 无；本函数仅比较字段、返回固定值或返回对象本身。
    def bind_tools(self, tools):
        """返回测试模型本身；真实工具仍由图执行器调用。"""
        return self

    # 函数说明：OfflineModel.ainvoke
    # 功能：返回下一条固定消息，序列耗尽表明测试模型和执行流程不符。
    # 内部调用：
    #   - next()：取迭代器的下一项；脚本模型用它取响应，页面测试用它定位匹配按钮。
    async def ainvoke(self, messages):
        """返回下一条固定消息，序列耗尽表明测试模型和执行流程不符。"""
        return next(self.messages)


# 函数说明：answer_consistent
# 功能：用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。
# 内部调用：
#   - re.finditer()：逐项返回匹配对象，用于从最终回复提取要与数据库核对的状态陈述。
#   - match.groups()：返回正则捕获组，如工单编号和声称的状态。
#   - claims.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - re.search()：查找第一处符合正则的内容；用于识别明确故障、失败反馈、禁止写操作或业务陈述。
#   - item.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
def answer_consistent(answer, tickets, confirmed=None):
    """功能：按句核对明确状态及建单编号；split/finditer 提取可识别陈述，数据库和成功确认提供证据，其他句子的否定词不能掩盖错误。"""
    records = {ticket["ticket_id"]: ticket for ticket in tickets}
    for sentence in re.split(r"[。！？\n]", answer):
        claims = list(
            re.finditer(
                r"(T\d+)\s*[，,·].{0,30}?当前状态[：:]\s*(待处理|处理中|待用户确认|已解决|已关闭)",
                sentence,
            )
        )
        for match in re.finditer(
            r"(T\d+).{0,15}?(?:修改为|改为|标记为|变为)(待处理|处理中|待用户确认|已解决|已关闭)",
            sentence,
        ):
            # 仅识别当前陈述附近的否定，不能用全文中的“不允许”跳过所有状态比较。
            local = sentence[max(0, match.start() - 8) : match.end()]
            if not re.search(r"不允许|不能|未完成|不要|不会", local):
                claims.append(match)
        for match in claims:
            ticket_id, status = match.groups()
            if ticket_id not in records or records[ticket_id]["status"] != status:
                return False
        creation = re.search(r"(?:已创建|创建.{0,6}成功|创建工单已完成)", sentence)
        if creation and not re.search(
            r"(?:未|没有|尚未|不能|不会)$", sentence[: creation.start()]
        ):
            evidence = {
                item["ticket"]["ticket_id"]
                for item in (confirmed or [])
                if item.get("success")
                and item.get("action") == "create_ticket"
                and item.get("ticket")
            }
            mentioned = set(re.findall(r"T\d+", sentence))
            if (
                not evidence
                or not mentioned <= evidence
                or not evidence <= records.keys()
            ):
                return False
    return True


# 函数说明：check_turn
# 功能：比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。
# 内部调用：
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - expected.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - answer.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - bool()：转换为布尔值；空值为 False，用于判断配置、结果或待确认记录是否存在。
#   - item.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - answer_consistent()：用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。
#   - all()：检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。
#   - outcome.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - checks.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
def check_turn(
    expected,
    calls,
    results,
    answer,
    tickets,
    *,
    before=None,
    confirmations=None,
    pending=None,
    reply_snapshots=None,
    proposals=None,
    audits=None,
    memory=None,
):
    """功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。"""
    before, confirmations, pending = before or [], confirmations or [], pending or []
    checks = {
        "row_count": len(tickets) == expected.get("rows", len(tickets)),
        "answer_present": bool(answer.strip()),
        "state_consistency": all(
            answer_consistent(
                item["answer"], item["tickets"], item.get("confirmations")
            )
            for item in reply_snapshots
        )
        if reply_snapshots is not None
        else answer_consistent(answer, tickets, confirmations),
    }
    if "allowed_tools" in expected:
        checks["allowed_tools"] = all(
            call["name"] in expected["allowed_tools"] for call in calls
        )
    if "answer_contains" in expected:
        checks["answer_contains"] = all(
            text in answer for text in expected["answer_contains"]
        )
    if "pending" in expected:
        checks["pending_count"] = len(pending) == expected["pending"]
    if expected.get("pending_before_confirm"):
        checks["confirmation_required"] = bool(confirmations) and any(
            outcome.get("state") == "awaiting_confirmation" for outcome in results
        )
        checks["no_write_before_confirm"] = all(
            outcome.get("state") != "executed" for outcome in results
        )
    if "faq_id" in expected:
        checks["applicable_faq"] = any(
            entry["id"] == expected["faq_id"]
            for outcome in results
            for entry in outcome.get("matches", [])
        )
    if expected.get("faq_empty"):
        checks["empty_faq"] = any(
            outcome.get("action") == "search_faq" and not outcome.get("matches")
            for outcome in results
        )
    if "tool_error" in expected:
        checks["tool_error"] = any(
            outcome.get("error") == expected["tool_error"] for outcome in results
        )
    if "search_count" in expected:
        checks["search_count"] = any(
            outcome.get("action") == "search_tickets"
            and len(outcome.get("tickets", [])) == expected["search_count"]
            for outcome in results
        )
    if expected.get("duplicate_required"):
        checks["duplicate_required"] = any(
            outcome.get("error") == "duplicate_confirmation_required"
            for outcome in confirmations
        )
    if expected.get("no_ticket_disclosure"):
        checks["no_ticket_disclosure"] = not any(
            outcome.get("ticket") or outcome.get("tickets") for outcome in results
        )
    target = (
        next(
            (
                ticket
                for ticket in tickets
                if ticket["ticket_id"] == expected.get("ticket_id")
            ),
            None,
        )
        if expected.get("ticket_id")
        else (tickets[-1] if tickets else None)
    )
    for field in (
        "status",
        "product_model",
        "priority",
        "contact",
        "manual",
        "assigned_to",
    ):
        if field in expected:
            checks[field] = target is not None and target[field] == expected[field]
    if "issue_contains" in expected:
        checks["issue_contains"] = (
            target is not None
            and expected["issue_contains"] in target["issue_description"]
        )
    if "issue_any" in expected:
        checks["issue_any"] = target is not None and any(
            term.casefold() in target["issue_description"].casefold()
            for term in expected["issue_any"]
        )
    if (
        any(outcome.get("state") == "awaiting_confirmation" for outcome in results)
        and not confirmations
    ):
        checks["unconfirmed_database_unchanged"] = before == tickets
    checks.update(
        assess_contract(
            expected,
            before=before,
            tickets=tickets,
            results=results,
            confirmations=confirmations,
            proposals=proposals or [],
            audits=audits,
            answer=answer,
            memory=memory or {},
        )
    )
    return {
        "checks": checks,
        "failures": classify_failures(checks),
        "automated_pass": all(checks.values()),
        "human_review": "pending",
    }


# 函数说明：seed_database
# 功能：为每个隔离评测创建账号和可选已知工单；种子是测试前置条件，不计为 Agent 完成。
# 内部调用：
#   - auth.create_user()：事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。
#   - case.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - storage.connect()：作为 with 上下文打开 SQLite，必要时迁移表结构；调用方完成后提交或回滚，最后关闭连接。
#   - db.execute()：在当前 SQLite 连接执行 SQL；占位符绑定业务值，事务语句控制提交边界。
#   - seed.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - storage.insert_ticket()：可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。
def seed_database(db_path, case):
    """功能：准备隔离前置条件；create_user 建测试账号，enumerate/insert_ticket 准备一张或多张种子工单，SQL 设置初始状态；种子不计为 Agent 完成。"""
    auth.create_user(
        "admin", "evaluation-only-password", "admin", db_path, bootstrap=True
    )
    for user in ("alice", "bob"):
        auth.create_user(user, "evaluation-only-password", db_path=db_path)
    auth.create_user(
        "tech", "evaluation-only-password", "technician", db_path, administrator="admin"
    )
    auth.create_user(
        "support", "evaluation-only-password", "support", db_path, administrator="admin"
    )
    seeds = case.get("seeds", [case["seed"]] if case.get("seed") else [])
    for index, seed in enumerate(seeds):
        with storage.connect(db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            ticket = storage.insert_ticket(
                db, seed, f"seed-request-{index}", seed.get("owner_id", "alice")
            )["ticket"]
            db.execute(
                "UPDATE tickets SET status=?,assigned_to=? WHERE ticket_id=?",
                (seed["status"], seed.get("assigned_to", ""), ticket["ticket_id"]),
            )


# 函数说明：run_case
# 功能：逐轮运行真正应用服务，测试驱动器模拟确认按钮；记录确认前后快照、工具轨迹和用量。
# 内部调用：
#   - asyncio.to_thread()：把传入的同步函数放到工作线程执行并异步等待，避免 SQLite 操作阻塞检查点所在的事件循环。
#   - case.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - sessions.create_thread()：验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
#   - enumerate()：遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。
#   - storage.list_tickets()：可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。
#   - sessions.begin_request()：在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。
#   - OfflineModel()：构造离线脚本模型：按本用例返回预设工具请求，再故意给出虚构成功文字；真实工具和执行层仍运行。
#   - run_request()：验证账号并获取请求租约，恢复已记录用量，通过 SQLite 检查点开始或续跑 LangGraph；保存最终回复、用量、耗时，失败时保留原请求供重试。
#   - sessions.timeline()：先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。
#   - actions.pending_actions()：检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。
#   - turn.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - actions.confirm_action()：页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。
#   - confirmations.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - actions.render_result()：完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。
#   - reply_snapshots.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - check_turn()：比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。
#   - turn['expect'].get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - sessions.get_thread()：按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - assessed['checks'].values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - all()：检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。
#   - report['turns'].append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
# 间接调用 / 回调：
#   - seed_database：由 asyncio.to_thread 调用/注册：为每个隔离评测创建账号和可选已知工单；种子是测试前置条件，不计为 Agent 完成。
async def run_case(
    case,
    db_path,
    mode="live",
    model_map=None,
    repetition=1,
    *,
    memory_mode=None,
    request_limits=None,
):
    """功能：驱动完整业务场景；seed_database 准备前置，run_request 执行/重放，confirm_action 模拟用户点击，check_turn 评分，SQLite 快照和审计保存证据。"""
    # 消融仅由隔离评测驱动器传入；不改变线上服务和默认回归行为。
    # save_memory 只重置结构化字段，聊天记录、摘要、检查点、权限和工单不变。
    if memory_mode not in {None, "on", "off"}:
        raise ValueError("memory_mode 必须是 on/off 或 None")
    await asyncio.to_thread(seed_database, db_path, case)
    user = case.get("user", "alice")
    thread_id = sessions.create_thread(user, db_path)
    context = Context(user_id=user, thread_id=thread_id, db_path=db_path)
    report = {
        "id": case["id"],
        "name": case["name"],
        "category": case["category"],
        "split": case.get("split", "regression"),
        "goal": case.get("goal", ""),
        "repetition": repetition,
        "turns": [],
    }
    for index, turn in enumerate(case["turns"]):
        memory_boundary = None
        if memory_mode is not None:
            previous_thread = sessions.get_thread(thread_id, user, db_path)
            if memory_mode == "off":
                sessions.save_memory(thread_id, user, {}, db_path)
            current_thread = sessions.get_thread(thread_id, user, db_path)
            memory_boundary = {
                "mode": memory_mode,
                "before": previous_thread["memory"],
                "after": current_thread["memory"],
                "transcript_unchanged": previous_thread["transcript"]
                == current_thread["transcript"],
                "summary_unchanged": previous_thread["summary"]
                == current_thread["summary"],
            }
        before = storage.list_tickets(db_path)
        with storage.connect(db_path) as db:
            audit_start = db.execute(
                "SELECT coalesce(max(event_id),0) FROM ticket_events"
            ).fetchone()[0]
        context.request_id = sessions.begin_request(
            thread_id, user, turn["input"], db_path
        )
        model_args = dict(request_limits or {})
        if mode == "offline":
            key = f"offline/{case['id']}/{repetition}/{index}"
            model_map[key] = OfflineModel(turn["offline_calls"])
            model_args["model"] = key
        output = await run_request(context.request_id, user, db_path, **model_args)
        replay_ok = None
        if turn.get("replay_request"):
            replay_before = storage.list_tickets(db_path)
            events_before = sessions.timeline(thread_id, user, db_path)
            replayed = await run_request(
                context.request_id, user, db_path, **model_args
            )
            replay_ok = (
                replayed == output
                and replay_before == storage.list_tickets(db_path)
                and events_before == sessions.timeline(thread_id, user, db_path)
            )
        events = [
            row
            for row in sessions.timeline(thread_id, user, db_path)
            if row["request_id"] == context.request_id
        ]
        calls = [
            {"name": row["name"], "args": row["args"]}
            for row in events
            if row["kind"] == "tool"
        ]
        results = [row["result"] for row in events if row["kind"] == "tool"]
        pending_before = actions.pending_actions(context)
        before_confirmation = storage.list_tickets(db_path)
        confirmations = []
        reply_snapshots = [{"answer": output["answer"], "tickets": before_confirmation}]
        if turn.get("confirm") and pending_before:
            for operation in pending_before * turn.get("confirm_repeats", 1):
                confirmations.append(
                    actions.confirm_action(
                        context,
                        operation["operation_id"],
                        accept_duplicate=turn["confirm"] == "accept_duplicate",
                        cancel=turn["confirm"] == "cancel",
                    )
                )
                reply_snapshots.append(
                    {
                        "answer": actions.render_result(confirmations[-1]),
                        "tickets": storage.list_tickets(db_path),
                        "confirmations": [confirmations[-1]],
                    }
                )
        tickets = storage.list_tickets(db_path)
        with storage.connect(db_path) as db:
            audits = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM ticket_events WHERE event_id>? ORDER BY event_id",
                    (audit_start,),
                )
            ]
        memory = sessions.get_thread(thread_id, user, db_path)["memory"]
        answer = output["answer"]
        if confirmations:
            answer += "\n" + "\n".join(
                actions.render_result(item) for item in confirmations
            )
        assessed = check_turn(
            turn["expect"],
            calls,
            results,
            answer,
            tickets,
            before=before,
            confirmations=confirmations,
            pending=actions.pending_actions(context),
            reply_snapshots=reply_snapshots,
            proposals=pending_before,
            audits=audits,
            memory=memory,
        )
        assessed["checks"]["execution_completed"] = output["success"]
        assessed["checks"]["proposal_did_not_write"] = before == before_confirmation
        if turn.get("confirm_repeats", 1) > 1:
            assessed["checks"]["idempotent_confirmation"] = (
                bool(confirmations)
                and all(
                    confirmation_facts(item) == confirmation_facts(confirmations[0])
                    for item in confirmations
                )
                and len(audits) == turn["expect"].get("audit_delta", 1)
            )
        if replay_ok is not None:
            assessed["checks"]["idempotent_request"] = replay_ok
        if turn["expect"].get("diagnosis_exhausted"):
            assessed["checks"]["diagnosis_exhausted"] = (
                sessions.get_thread(thread_id, user, db_path)["memory"][
                    "diagnosis_exhausted"
                ]
                and "可靠排查步骤已尝试完" in answer
            )
        if "tried_count_min" in turn["expect"]:
            assessed["checks"]["tried_steps_retained"] = (
                len(
                    sessions.get_thread(thread_id, user, db_path)["memory"][
                        "troubleshooting_steps"
                    ]
                )
                >= turn["expect"]["tried_count_min"]
            )
        assessed["automated_pass"] = all(assessed["checks"].values())
        assessed["failures"] = classify_failures(assessed["checks"])
        report["turns"].append(
            {
                **assessed,
                "input": turn["input"],
                "request_id": context.request_id,
                "answer": answer,
                "calls": calls,
                "results": results,
                "confirmations": confirmations,
                "database_before": before,
                "before_confirmation": before_confirmation,
                "reply_snapshots": reply_snapshots,
                "database": tickets,
                "output": output,
                "pending": pending_before,
                "audit_events": audits,
                "thread_memory": sessions.get_thread(thread_id, user, db_path)[
                    "memory"
                ],
                **({"memory_boundary": memory_boundary} if memory_boundary else {}),
            }
        )
        if not output["success"]:
            break
    report["automated_pass"] = len(report["turns"]) == len(case["turns"]) and all(
        turn["automated_pass"] for turn in report["turns"]
    )
    return report


# 函数说明：summarize
# 功能：从逐轮报告计算业务成功率、状态一致率、工具合法率、耗时与 token；保留分母。
# 内部调用：
#   - result.get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
#   - turn['output'].get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - turn['output'].get(...).get()：按键读取字典或映射里的值，键不存在时返回指定默认值（未指定则为 None）。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - statistics.mean()：计算全部已运行轮次的平均执行耗时。
#   - round()：按指定小数位四舍五入，使相似度、费用或耗时便于展示。
def summarize(cases):
    """功能：统计单次任务成功及用量；grouped_metrics 分类失败和重复运行稳定性，sorted/mean 计算 P95/均值，sum 保留通过数与总数。"""
    turns = [turn for case in cases for turn in case["turns"]]
    results = [result for turn in turns for result in turn["results"]]
    factual = [
        turn
        for turn in turns
        if any(
            result.get("ticket") or "tickets" in result for result in turn["results"]
        )
        or turn["confirmations"]
        or not turn["checks"]["state_consistency"]
    ]
    legal = sum(
        result.get("success", False)
        or result.get("error")
        in {"no_matching_faq", "not_found", "missing_model", "missing_issue"}
        for result in results
    )
    total_tokens = sum(
        turn["output"].get("usage", {}).get("total_tokens", 0) for turn in turns
    )
    elapsed = sorted(turn["output"]["elapsed_ms"] for turn in turns)
    return {
        **grouped_metrics(cases),
        "task_success": {
            "passed": sum(case["automated_pass"] for case in cases),
            "total": len(cases),
        },
        "state_consistency": {
            "passed": sum(turn["checks"]["state_consistency"] for turn in factual),
            "total": len(factual),
        },
        "legal_tool_calls": {"passed": legal, "total": len(results)},
        "mean_elapsed_ms": round(
            statistics.mean(turn["output"]["elapsed_ms"] for turn in turns), 2
        )
        if turns
        else None,
        "tool_calls": len(results),
        "p95_elapsed_ms": elapsed[max(0, (len(elapsed) * 95 + 99) // 100 - 1)]
        if elapsed
        else None,
        "estimated_usage_turns": sum(
            turn["output"].get("usage", {}).get("estimated_tokens", False)
            for turn in turns
        ),
        "total_tokens": total_tokens,
        "cost_estimate": None
        if any(turn["output"].get("cost_estimate") is None for turn in turns)
        else sum(turn["output"]["cost_estimate"] for turn in turns),
    }


# 函数说明：main
# 功能：解析 CLI，按有限并发运行隔离用例并增量保存；offline 与 live 的证据明确分开。
# 内部调用：
#   - argparse.ArgumentParser()：构造命令行参数解析器，生成帮助信息并校验参数。
#   - parser.add_argument()：登记 mode、case、output、concurrency 等可用命令行选项。
#   - parser.parse_args()：解析用户实际传入的命令行参数，返回可按属性读取的配置。
#   - load_dotenv()：从 .env 加载配置到进程环境，默认不覆盖已经存在的环境变量。
#   - (storage.ROOT / 'data/eval_cases.json').read_text()：读取 UTF-8 文本，供解析 FAQ 或固定评测用例。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - args.case.split()：按指定分隔符拆分文本，解析 provider/model、配置列表或密码盐前缀。
#   - parser.error()：输出无效参数错误并终止脚本，避免把空用例集合误报为通过。
#   - Path()：构造文件路径对象，便于拼接路径、判断绝对路径和读取本地文件。
#   - output.parent.mkdir()：创建输出或数据库父目录；parents/exist_ok 允许补齐父级并复用现有目录。
#   - datetime.now()：读取当前日期时间；传入 UTC 以统一数据库时间与有效期。
#   - datetime.now(...).isoformat()：把日期时间转换为包含时区的 ISO 文本，便于持久化和过期时间比较。
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - path.relative_to()：把路径转换为相对项目根目录的路径，作为评测源码指纹的键。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - path.read_bytes()：读取源文件的原始字节，生成可复查的 SHA256 指纹。
#   - hashlib.sha256()：计算字节数据的 SHA256 摘要，用于令牌检索、确认参数一致性或文件指纹。
#   - hashlib.sha256(...).hexdigest()：把哈希对象的结果转换为十六进制文本，用于存储与比较。
#   - storage.ROOT.glob()：枚举符合模式的源文件，形成评测时记录指纹的文件清单。
#   - sorted()：返回按默认次序或 key 规则排好的新列表，不原地修改原列表。
#   - Context(...).model.startswith()：判断文本是否带指定前缀；此处按模型提供商选择需要读取的密钥。
#   - os.getenv()：读取环境变量，可指定默认值；读取的是当前进程配置。
#   - os.getenv(...).strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - json.dumps()：把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。
#   - output.write_text()：把当前报告写入本地文件，以便中途或完成后复查。
#   - importlib.import_module()：按模块名导入模块；评测/测试用来替换模型加载入口，不加载用户输入的任意模块。
#   - min()：选择最小值；用于挑选负载较低的维修人员或限制并发上限。
#   - max()：选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。
#   - asyncio.Semaphore()：创建异步信号量，限制同时运行的场景数量。
#   - tempfile.TemporaryDirectory()：创建隔离的临时目录，with 退出时自动清理评测数据库。
#   - evaluate()：受信号量限制运行一个用例并增量写报告；并发用例使用不同 SQLite 文件。
#   - asyncio.gather()：并发等待多个场景协程；具体并发数量仍由 Semaphore 控制。
#   - summarize()：从逐轮报告计算业务成功率、状态一致率、工具合法率、耗时与 token；保留分母。
#   - all()：检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。
#   - print()：向终端输出评测进度、证据或结果，便于观察脚本执行情况。
# 匿名函数：
#   - lambda name: model_map[name]：仅在离线评测期间替换模型加载器，按场景键取得已准备好的 OfflineModel。
async def main():
    """功能：运行所选评测；validate_cases 先校验契约，Semaphore/gather 限并发与重复次数，run_case 执行业务，summarize 汇总并保存源码指纹。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--case", help="逗号分隔的用例编号，例如 01,18,46")
    parser.add_argument("--output", default="")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--split", choices=["all", "regression", "challenge"], default="all"
    )
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    args = parser.parse_args()
    load_dotenv(storage.ROOT / ".env")
    cases = json.loads((storage.ROOT / "data/eval_cases.json").read_text())
    validate_cases(cases)
    if args.split != "all":
        cases = [case for case in cases if case["split"] == args.split]
    if args.case:
        requested = {item.strip() for item in args.case.split(",")}
        if missing := requested - {case["id"] for case in cases}:
            parser.error("当前分组不存在用例：" + ",".join(sorted(missing)))
        cases = [case for case in cases if case["id"] in requested]
        if not cases:
            parser.error("没有匹配用例")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = Path(args.output or f"reports/{args.mode}-contracts-{stamp}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "time": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "model": Context().model if args.mode == "live" else "scripted-offline",
        "status": "running",
        "human_review": "pending",
        "contract_version": "2026-10-10.1",
        "scope": "scripted execution-layer checks"
        if args.mode == "offline"
        else "live model through service; confirmation by test driver",
        "split": args.split,
        "repeat": args.repeat,
        "planned_cases": len(cases),
        "planned_runs": len(cases) * args.repeat,
        "cases": [],
        "source_sha256": {
            str(path.relative_to(storage.ROOT)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(
                [
                    *storage.ROOT.glob("src/react_agent/*.py"),
                    storage.ROOT / "scripts/evaluate.py",
                    storage.ROOT / "data/eval_cases.json",
                    storage.ROOT / "data/faq.json",
                ]
            )
        },
    }
    key = (
        "DEEPSEEK_API_KEY"
        if Context().model.startswith("deepseek/")
        else "OPENAI_API_KEY"
    )
    if args.mode == "live" and not os.getenv(key, "").strip():
        report["status"] = "not_run_missing_credentials"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    model_map = {}
    graph_module = importlib.import_module("react_agent.graph")
    original = graph_module.load_chat_model
    if args.mode == "offline":
        graph_module.load_chat_model = lambda name: model_map[name]
    semaphore = asyncio.Semaphore(max(1, min(args.concurrency, 4)))

    # 函数说明：main.evaluate
    # 功能：受信号量限制运行一个用例并增量写报告；并发用例使用不同 SQLite 文件。
    # 内部调用：
    #   - Path()：构造文件路径对象，便于拼接路径、判断绝对路径和读取本地文件。
    #   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
    #   - run_case()：逐轮运行真正应用服务，测试驱动器模拟确认按钮；记录确认前后快照、工具轨迹和用量。
    #   - type()：取得对象的类型；此处主要用异常类型名记录错误类别。
    #   - report['cases'].append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
    #   - report['cases'].sort()：按 key 原地排序列表；评测报告用它保持用例编号的次序。
    #   - json.dumps()：把 Python 数据编码为 JSON 文本，供持久化、工具消息和评测报告使用。
    #   - output.write_text()：把当前报告写入本地文件，以便中途或完成后复查。
    #   - print()：向终端输出评测进度、证据或结果，便于观察脚本执行情况。
    # 匿名函数：
    #   - lambda item: item['id']：由列表 sort 调用，按用例编号保持报告顺序，不改变用例结果。
    async def evaluate(case, folder, repetition):
        """受信号量限制运行一个用例并增量写报告；并发用例使用不同 SQLite 文件。"""
        async with semaphore:
            try:
                result = await run_case(
                    case,
                    str(Path(folder) / f"{case['id']}-{repetition}.db"),
                    args.mode,
                    model_map,
                    repetition,
                )
            except Exception as error:
                result = {
                    "id": case["id"],
                    "name": case["name"],
                    "category": case["category"],
                    "split": case["split"],
                    "repetition": repetition,
                    "automated_pass": False,
                    "turns": [],
                    "error_code": type(error).__name__,
                }
            report["cases"].append(result)
            report["cases"].sort(key=lambda item: (item["id"], item["repetition"]))
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(
                f"{case['id']} run={repetition}",
                "PASS" if result["automated_pass"] else "FAIL",
                case["name"],
                flush=True,
            )

    try:
        with tempfile.TemporaryDirectory(prefix="ticket-evaluation-") as folder:
            await asyncio.gather(
                *(
                    evaluate(case, folder, repetition)
                    for case in cases
                    for repetition in range(1, args.repeat + 1)
                )
            )
    finally:
        graph_module.load_chat_model = original
    report["metrics"] = summarize(report["cases"])
    report["status"] = (
        "passed"
        if all(case["automated_pass"] for case in report["cases"])
        else "failed"
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["metrics"], ensure_ascii=False), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
