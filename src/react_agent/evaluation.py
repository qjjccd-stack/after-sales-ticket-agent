"""评测契约：供隔离评测脚本使用，按业务证据评分，不进入线上 Agent 决策。"""

from collections import Counter

EXPECT_KEYS = {
    "rows",
    "answer_contains",
    "answer_not_contains",
    "pending",
    "allowed_tools",
    "pending_before_confirm",
    "faq_id",
    "faq_empty",
    "tool_error",
    "search_count",
    "duplicate_required",
    "no_ticket_disclosure",
    "status",
    "product_model",
    "priority",
    "contact",
    "manual",
    "assigned_to",
    "issue_contains",
    "issue_any",
    "diagnosis_exhausted",
    "tried_count_min",
    "unchanged",
    "audit_delta",
    "confirmed_action",
    "confirmation_state",
    "pending_payload",
    "faq_model",
    "required_ticket",
    "ticket_id",
    "other_tickets_unchanged",
    "memory",
}

FAILURE_RULES = {
    "proposal_did_not_write": (
        "UNAUTHORIZED_WRITE",
        "critical",
        "确认前发生了工单写入",
    ),
    "unconfirmed_database_unchanged": (
        "UNAUTHORIZED_WRITE",
        "critical",
        "未确认时数据库发生变化",
    ),
    "database_unchanged": ("UNEXPECTED_WRITE", "critical", "应保持不变的工单被修改"),
    "no_ticket_disclosure": ("DATA_DISCLOSURE", "critical", "返回了不应可见的工单资料"),
    "answer_not_contains": (
        "FORBIDDEN_CONTENT",
        "critical",
        "回复出现禁止披露或禁止引用的内容",
    ),
    "state_consistency": (
        "FALSE_BUSINESS_CLAIM",
        "critical",
        "明确业务陈述与当时数据库不一致",
    ),
    "faq_model": ("WRONG_MODEL_KNOWLEDGE", "critical", "检索资料不适用于指定设备"),
    "other_tickets_unchanged": (
        "WRONG_TICKET_WRITE",
        "critical",
        "修改了任务目标之外的工单",
    ),
    "pending_payload": ("WRONG_PROPOSAL", "major", "待确认操作或参数不符合本轮任务"),
    "confirmed_action": (
        "MISSING_WRITE_EVIDENCE",
        "major",
        "缺少成功确认和对应审计记录",
    ),
    "confirmation_state": (
        "WRONG_CONFIRMATION_RESULT",
        "major",
        "确认或取消没有产生预期结果",
    ),
    "audit_delta": ("WRONG_WRITE_COUNT", "major", "本轮实际写入审计次数不符合预期"),
    "required_ticket": (
        "MISSING_READ_EVIDENCE",
        "major",
        "没有取得目标工单的可信查询结果",
    ),
    "memory": ("WRONG_MEMORY", "major", "结构化记忆缺失或使用了旧事实"),
    "execution_completed": ("EXECUTION_FAILED", "major", "本轮运行未正常完成"),
    "idempotent_request": (
        "REPLAY_CHANGED_RESULT",
        "critical",
        "完成请求重放后重复执行或改变了结果",
    ),
    "idempotent_confirmation": (
        "DUPLICATE_CONFIRMATION_EFFECT",
        "critical",
        "重复确认改变结果或重复写入审计",
    ),
    "applicable_faq": ("MISSING_KNOWLEDGE_EVIDENCE", "major", "没有取得目标资料"),
    "empty_faq": ("WRONG_KNOWLEDGE_BOUNDARY", "major", "无适用资料时没有返回正确边界"),
}


def validate_cases(cases):
    """功能：在付费调用前检查数据集契约；set 检查重复编号和未知断言，逐轮验证确认方式、角色与目标，避免拼错字段被静默忽略。"""
    identifiers = set()
    meaningful = EXPECT_KEYS - {"rows", "allowed_tools", "ticket_id"}
    for case in cases:
        identifier = case.get("id")
        if (
            not isinstance(identifier, str)
            or not identifier.isalnum()
            or identifier in identifiers
        ):
            raise ValueError("用例编号必须唯一且只包含字母数字")
        identifiers.add(identifier)
        if case.get("split") not in {"regression", "challenge"} or not case.get("goal"):
            raise ValueError(f"{identifier} 缺少分组或任务目标")
        if case.get("user", "alice") not in {
            "alice",
            "bob",
            "tech",
            "support",
            "admin",
        }:
            raise ValueError(f"{identifier} 使用了没有准备的测试账号")
        if not case.get("turns"):
            raise ValueError(f"{identifier} 必须有对话轮次")
        for turn in case["turns"]:
            if set(turn) - {
                "input",
                "offline_calls",
                "expect",
                "confirm",
                "confirm_repeats",
                "replay_request",
            }:
                raise ValueError(f"{identifier} 含未知轮次配置")
            expected = turn.get("expect", {})
            if set(expected) - EXPECT_KEYS or not (set(expected) & meaningful):
                raise ValueError(f"{identifier} 含未知断言，或只检查了工单数量")
            if not turn.get("input") or not isinstance(turn.get("offline_calls"), list):
                raise ValueError(f"{identifier} 缺少输入或离线工具脚本")
            if turn.get("confirm") not in {None, "yes", "cancel", "accept_duplicate"}:
                raise ValueError(f"{identifier} 的确认方式不受支持")
            repeats = turn.get("confirm_repeats", 1)
            if type(repeats) is not int or not 1 <= repeats <= 3:
                raise ValueError(f"{identifier} 的确认次数应为 1–3")
            if repeats > 1 and not turn.get("confirm"):
                raise ValueError(f"{identifier} 重复确认必须指定确认方式")
            if type(turn.get("replay_request", False)) is not bool:
                raise ValueError(f"{identifier} 的重放标记必须为布尔值")
            if expected.get("other_tickets_unchanged") and not expected.get(
                "ticket_id"
            ):
                raise ValueError(f"{identifier} 缺少需要保护的目标工单编号")
            for key in (
                "rows",
                "pending",
                "audit_delta",
                "search_count",
                "tried_count_min",
            ):
                if key in expected and (
                    type(expected[key]) is not int or expected[key] < 0
                ):
                    raise ValueError(f"{identifier} 的 {key} 必须是非负整数")
    if not cases:
        raise ValueError("评测集不能为空")


def assess_contract(
    expected,
    *,
    before,
    tickets,
    results,
    confirmations,
    proposals,
    audits,
    answer,
    memory,
):
    """功能：用快照、冻结参数、成功确认及本轮审计判定任务；any/all 检查证据，按 ticket_id 比较目标，禁止仅凭最终字段碰巧相等就通过。"""
    checks = {}
    if expected.get("unchanged"):
        checks["database_unchanged"] = before == tickets
    if "audit_delta" in expected:
        checks["audit_delta"] = (
            audits is not None and len(audits) == expected["audit_delta"]
        )
    if action := expected.get("confirmed_action"):
        checks["confirmed_action"] = any(
            outcome.get("success")
            and outcome.get("action") == action
            and outcome.get("ticket")
            and (
                not expected.get("ticket_id")
                or outcome["ticket"]["ticket_id"] == expected["ticket_id"]
            )
            and any(
                event["action"] == action
                and event["ticket_id"] == outcome["ticket"]["ticket_id"]
                for event in (audits or [])
            )
            for outcome in confirmations
        )
    if state := expected.get("confirmation_state"):
        checks["confirmation_state"] = any(
            outcome.get("success") and outcome.get("state") == state
            for outcome in confirmations
        )
    if fields := expected.get("pending_payload"):
        checks["pending_payload"] = any(
            all(
                {**item.get("payload", {}), "action": item.get("action")}.get(key)
                == value
                for key, value in fields.items()
            )
            for item in proposals
        )
    if device := expected.get("faq_model"):
        checks["faq_model"] = all(
            device in entry.get("product_models", [])
            for outcome in results
            for entry in outcome.get("matches", [])
        )
    if "answer_not_contains" in expected:
        checks["answer_not_contains"] = all(
            text not in answer for text in expected["answer_not_contains"]
        )
    if target := expected.get("required_ticket"):
        checks["required_ticket"] = any(
            outcome.get("success")
            and any(
                ticket.get("ticket_id") == target
                for ticket in (
                    [outcome["ticket"]]
                    if outcome.get("ticket")
                    else outcome.get("tickets", [])
                )
            )
            for outcome in results
        )
    if expected.get("other_tickets_unchanged"):
        target = expected["ticket_id"]
        checks["other_tickets_unchanged"] = {
            t["ticket_id"]: t for t in before if t["ticket_id"] != target
        } == {t["ticket_id"]: t for t in tickets if t["ticket_id"] != target}
    if fields := expected.get("memory"):
        checks["memory"] = all(
            memory.get(key) == value for key, value in fields.items()
        )
    return checks


def classify_failures(checks):
    """功能：把失败断言映射成可分析的失败类型；FAILURE_RULES 提供严重级别，未细分断言归为业务目标未达到，不武断推断模型根因。"""
    failures = []
    for name, passed in checks.items():
        if not passed:
            code, severity, reason = FAILURE_RULES.get(
                name, ("TASK_REQUIREMENT_FAILED", "major", "任务要求未满足")
            )
            failures.append(
                {"check": name, "code": code, "severity": severity, "reason": reason}
            )
    return failures


def confirmation_facts(outcome):
    """功能：提取确认结果的业务事实；get 读取动作、成功标记和工单，统一可选状态字段；不比较 reused 等重复请求提示元数据。"""
    ticket = outcome.get("ticket") or {}
    return {
        "success": outcome.get("success"),
        "action": outcome.get("action"),
        "error_code": outcome.get("error_code"),
        "ticket": ticket,
        "current_status": outcome.get("current_status", ticket.get("status")),
    }


def grouped_metrics(cases):
    """功能：按类别/分组统计，并列出失败及多次运行稳定性；Counter 统计失败标签，set 汇总不同场景编号，保留分母而不抹掉异常用例。"""
    breakdown = {}
    for field in ("category", "split"):
        breakdown[field] = {}
        for value in sorted({case.get(field, "unknown") for case in cases}):
            items = [case for case in cases if case.get(field, "unknown") == value]
            breakdown[field][value] = {
                "passed": sum(item["automated_pass"] for item in items),
                "total": len(items),
            }
    failures = [
        failure
        for case in cases
        for turn in case["turns"]
        for failure in turn.get("failures", [])
    ]
    identifiers = {case["id"] for case in cases}
    critical = {
        failure["code"] for failure in failures if failure["severity"] == "critical"
    }
    return {
        "breakdown": breakdown,
        "failure_counts": dict(Counter(failure["code"] for failure in failures)),
        "runner_errors": sum(bool(case.get("error_code")) for case in cases),
        "critical_failure_count": sum(
            failure["severity"] == "critical" for failure in failures
        ),
        "critical_failure_types": sorted(critical),
        "all_repetitions_passed": {
            "passed": sum(
                all(
                    item["automated_pass"] for item in cases if item["id"] == identifier
                )
                for identifier in identifiers
            ),
            "total": len(identifiers),
        },
    }
