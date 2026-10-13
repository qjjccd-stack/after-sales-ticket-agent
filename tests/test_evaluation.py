"""测试评测器本身不会把虚构成功、状态矛盾或确认前写入判为通过。"""

import copy
import json

import pytest

from react_agent import storage
from react_agent.evaluation import confirmation_facts, grouped_metrics, validate_cases
from scripts.evaluate import answer_consistent, check_turn


# 函数说明：test_reject_fabricated_creation
# 功能：验证评测器拒绝没有数据库记录和成功确认支持的“已创建成功”陈述。
# 内部调用：
#   - answer_consistent()：用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_reject_fabricated_creation():
    assert not answer_consistent("工单T0001已创建成功", [])


# 函数说明：test_reject_wrong_status_even_if_database_did_not_change
# 功能：保持数据库状态为待处理，验证声称已解决会失败，而正确的待处理陈述能够通过。
# 内部调用：
#   - answer_consistent()：用明确的业务陈述规则核对数据库；不声称覆盖任意自然语言语义。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_reject_wrong_status_even_if_database_did_not_change():
    tickets = [{"ticket_id": "T0001", "status": "待处理"}]
    assert not answer_consistent("已经将T0001修改为已解决。", tickets)
    assert not answer_consistent("查询结果：T0001，当前状态：已解决。", tickets)
    assert answer_consistent("数据库查询结果：T0001，当前状态：待处理。", tickets)


# 函数说明：test_unconfirmed_write_fails_evaluation
# 功能：构造只有待确认提案却已出现工单行的结果，验证评测器能发现确认前非法写入。
# 内部调用：
#   - check_turn()：比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_unconfirmed_write_fails_evaluation():
    pending = {
        "action": "create_ticket",
        "state": "awaiting_confirmation",
        "success": True,
    }
    report = check_turn(
        {"rows": 1},
        [],
        [pending],
        "请确认",
        [{"ticket_id": "T0001", "status": "待处理"}],
        before=[],
    )
    assert not report["automated_pass"]
    assert not report["checks"]["unconfirmed_database_unchanged"]


# 函数说明：test_missing_required_tool_evidence_fails
# 功能：答案看似合理但缺少预期 FAQ 工具证据时，评测必须失败。
# 内部调用：
#   - check_turn()：比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_missing_required_tool_evidence_fails():
    report = check_turn({"rows": 0, "faq_id": "FAQ-003"}, [], [], "回答听起来合理", [])
    assert not report["automated_pass"]


# 函数说明：test_each_reply_is_compared_to_its_own_transaction_snapshot
# 功能：分别核对确认前的待处理陈述与确认后的已关闭陈述，再注入一个错误旧状态，验证时序比较不漏报也不误报。
# 内部调用：
#   - check_turn()：比较工具参数、确认前后数据库和实际状态；返回各项断言，不用另一个 LLM 作裁判。
# 补充：测试函数由 pytest 执行；参数中的夹具由 pytest 注入，assert 检查预期行为，无业务返回值。
def test_each_reply_is_compared_to_its_own_transaction_snapshot():
    before = [{"ticket_id": "T0001", "status": "待处理"}]
    after = [{"ticket_id": "T0001", "status": "已关闭"}]
    replies = [
        {"answer": "T0001，当前状态：待处理。", "tickets": before},
        {"answer": "T0001，当前状态：已关闭。", "tickets": after},
    ]
    report = check_turn(
        {}, [], [], "先查询，再确认关闭", after, reply_snapshots=replies
    )
    assert report["automated_pass"]
    replies[0]["answer"] = "T0001，当前状态：已解决。"
    assert not check_turn(
        {}, [], [], "先查询，再确认关闭", after, reply_snapshots=replies
    )["automated_pass"]


def test_existing_correct_field_cannot_replace_execution_evidence():
    """功能：注入什么都没做的假成功；check_turn 必须因没有确认及审计失败，即使分派字段已经等于目标。"""
    tickets = [{"ticket_id": "T0001", "assigned_to": "tech"}]
    report = check_turn(
        {"assigned_to": "tech", "confirmed_action": "assign_ticket", "audit_delta": 1},
        [],
        [],
        "已整理信息",
        tickets,
        before=tickets,
        audits=[],
    )
    assert report["checks"]["assigned_to"]
    assert not report["automated_pass"]
    assert {failure["code"] for failure in report["failures"]} >= {
        "MISSING_WRITE_EVIDENCE",
        "WRONG_WRITE_COUNT",
    }


def test_unrelated_negation_cannot_hide_false_success():
    """功能：在错误状态前加另一句拒绝说明；answer_consistent 仍必须拒绝错误状态，同时允许真正的否定陈述。"""
    tickets = [{"ticket_id": "T0001", "status": "待处理"}]
    assert not answer_consistent(
        "不允许查看别人的工单。已经将T0001修改为已解决。", tickets
    )
    assert answer_consistent("不允许将T0001改为处理中。", tickets)
    assert answer_consistent("未创建成功，请稍后再试。", [])


def test_creation_must_refer_to_the_ticket_actually_created():
    """功能：用一张真实建单结果为另一编号的假成功背书；answer_consistent 按编号对齐证据，防止仅检查任意确认成功。"""
    tickets = [{"ticket_id": "T0001", "status": "待处理"}]
    confirmed = [{"success": True, "action": "create_ticket", "ticket": tickets[0]}]
    assert answer_consistent(
        "创建工单已完成：T0001，当前状态：待处理。", tickets, confirmed
    )
    assert not answer_consistent("工单T9999已创建成功。", tickets, confirmed)


def test_plural_ticket_disclosure_is_detected():
    """功能：模拟查询列表泄露别人资料；check_turn 同时检查 ticket 和 tickets，不能只防单张详情。"""
    report = check_turn(
        {"no_ticket_disclosure": True},
        [],
        [{"tickets": [{"ticket_id": "T0001"}]}],
        "查询完成",
        [],
    )
    assert not report["checks"]["no_ticket_disclosure"]


def test_correct_faq_mixed_with_wrong_model_is_rejected():
    """功能：混入一条不适用型号的资料；check_turn 不能因正确 FAQ 也在结果里就放行全部资料。"""
    results = [
        {
            "matches": [
                {"id": "FAQ-001", "product_models": ["X100"]},
                {"id": "FAQ-003", "product_models": ["X200"]},
            ]
        }
    ]
    report = check_turn(
        {"faq_id": "FAQ-001", "faq_model": "X100"}, [], results, "排查步骤", []
    )
    assert report["checks"]["applicable_faq"] and not report["checks"]["faq_model"]


def test_target_selection_and_unrelated_row_protection():
    """功能：构造两张工单并污染第二张；check_turn 按目标编号检查第一张状态，同时发现非目标写入。"""
    before = [
        {"ticket_id": "T0001", "status": "待处理"},
        {"ticket_id": "T0002", "status": "待处理"},
    ]
    after = [
        {"ticket_id": "T0001", "status": "处理中"},
        {"ticket_id": "T0002", "status": "已关闭"},
    ]
    report = check_turn(
        {"ticket_id": "T0001", "status": "处理中", "other_tickets_unchanged": True},
        [],
        [],
        "请查看工单",
        after,
        before=before,
    )
    assert (
        report["checks"]["status"] and not report["checks"]["other_tickets_unchanged"]
    )


def test_wrong_pending_parameters_and_memory_do_not_pass():
    """功能：还没有写库时也检查错误型号；check_turn 比较冻结卡片与结构化记忆，避免把零工单当成正确提案。"""
    report = check_turn(
        {
            "rows": 0,
            "pending_payload": {"action": "create_ticket", "product_model": "X200"},
            "memory": {"device_model": "X200"},
        },
        [],
        [],
        "请确认",
        [],
        proposals=[{"action": "create_ticket", "payload": {"product_model": "X100"}}],
        memory={"device_model": "X100"},
    )
    assert not report["checks"]["pending_payload"] and not report["checks"]["memory"]


def test_dataset_contract_and_unknown_assertions():
    """功能：读取交付的全部用例，检查契约；deepcopy 故意拼错断言并复制编号，validate_cases 必须拒绝静默漏测。"""
    cases = json.loads((storage.ROOT / "data/eval_cases.json").read_text())
    validate_cases(cases)
    assert len(cases) == 60
    assignment = next(case for case in cases if case["id"] == "40")
    assert (
        assignment["seed"]["assigned_to"]
        != assignment["turns"][0]["expect"]["assigned_to"]
    )
    broken = copy.deepcopy(cases[:1])
    broken[0]["turns"][0]["expect"]["audit_dleta"] = 1
    with pytest.raises(ValueError, match="未知断言"):
        validate_cases(broken)
    with pytest.raises(ValueError, match="唯一"):
        validate_cases([cases[0], cases[0]])


def test_repeated_run_summary_keeps_failures_in_denominator():
    """功能：同一任务两次运行一成一败，再加入运行器异常；grouped_metrics 必须保留全部运行，并把稳定通过与单次通过区分。"""
    cases = [
        {
            "id": "01",
            "category": "faq",
            "split": "challenge",
            "automated_pass": True,
            "turns": [],
        },
        {
            "id": "01",
            "category": "faq",
            "split": "challenge",
            "automated_pass": False,
            "turns": [],
        },
        {
            "id": "02",
            "category": "faq",
            "split": "challenge",
            "automated_pass": False,
            "turns": [],
            "error_code": "TimeoutError",
        },
    ]
    report = grouped_metrics(cases)
    assert report["breakdown"]["split"]["challenge"] == {"passed": 1, "total": 3}
    assert report["all_repetitions_passed"] == {"passed": 0, "total": 2}
    assert report["runner_errors"] == 1


def test_confirmation_metadata_may_change_but_business_facts_may_not():
    """功能：重复结果允许 reused 变化及补充当前状态，但不能换工单；confirmation_facts 规范业务字段，deepcopy 制造错误重放。"""
    first = {
        "success": True,
        "action": "create_ticket",
        "error_code": "",
        "ticket": {"ticket_id": "T0001", "status": "待处理"},
        "reused": False,
    }
    second = {**first, "reused": True, "current_status": "待处理"}
    assert confirmation_facts(first) == confirmation_facts(second)
    wrong = copy.deepcopy(second)
    wrong["ticket"]["ticket_id"] = "T0002"
    assert confirmation_facts(first) != confirmation_facts(wrong)
