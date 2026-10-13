"""消融实验自身的回归：不能删聊天、用内部字段作弊，或把未运行/估算值冒充真实模型结果。"""

import asyncio
import importlib
import json
from copy import deepcopy

import pytest

from react_agent import storage
from scripts.evaluate import run_case
from scripts.evaluate_memory import (
    assess_trajectory,
    summarize_ablation,
    validate_ablation_cases,
)


def fixtures():
    """功能：读取冻结的场景与 FAQ；read_text/json.loads 还原文件，供测试复用真实业务数据。"""
    return (
        json.loads((storage.ROOT / "data/memory_ablation_cases.json").read_text()),
        json.loads((storage.ROOT / "data/faq.json").read_text()),
    )


def test_ablation_has_fixed_inputs_and_no_internal_memory_oracle():
    """功能：validate_cases 检查业务契约，再确认样本数量及断言不依赖被关闭的内部记忆字段。"""
    cases, _ = fixtures()
    validate_ablation_cases(cases)
    assert len(cases) == 6
    assert sum(len(case["turns"]) for case in cases) == 22
    assert not any(
        set(turn["expect"]) & {"memory", "tried_count_min", "diagnosis_exhausted"}
        for case in cases
        for turn in case["turns"]
    )


def test_memory_off_preserves_history_and_repetition_is_observable(
    monkeypatch, tmp_path
):
    """功能：run_case 跑两组真实工具链；assess_trajectory 从回复独立判重，同时核对 off 边界清空且聊天/摘要原样保留。"""
    cases, faq = fixtures()
    case = cases[-1]
    model_map = {}
    graph = importlib.import_module("react_agent.graph")
    monkeypatch.setattr(graph, "load_chat_model", lambda name: model_map[name])
    results = {}
    for condition in ("on", "off"):
        result = asyncio.run(
            run_case(
                case,
                str(tmp_path / f"{condition}.db"),
                "offline",
                model_map,
                memory_mode=condition,
            )
        )
        results[condition] = assess_trajectory(case, result, faq)
    assert results["on"]["automated_pass"]
    assert not results["off"]["automated_pass"]
    assert results["on"]["repeated_failed_recommendations"] == 0
    assert results["off"]["repeated_failed_recommendations"] == 3
    for turn in results["off"]["turns"]:
        boundary = turn["memory_boundary"]
        assert boundary["transcript_unchanged"] and boundary["summary_unchanged"]
        assert boundary["after"]["device_model"] is None
        assert boundary["after"]["troubleshooting_steps"] == []
        assert turn["checks"]["proposal_did_not_write"]
    # 脚本模型两组均能建单；关闭组失败原因是实际重复推荐，不是“没有 memory”。
    assert results["off"]["turns"][-1]["database"][0]["product_model"] == "X200"


def test_repetition_scoring_requires_actual_user_failure_feedback():
    """功能：deepcopy 构造只差用户反馈的轨迹；assess_trajectory 不把普通重复展示误称为重复推荐已失败步骤。"""
    cases, faq = fixtures()
    case = deepcopy(cases[-1])
    case["turns"] = case["turns"][:2]
    answer = "请先尝试：" + faq[2]["steps"][0]["text"] + "\n来源：FAQ-003"
    turn = {
        "output": {"answer": answer},
        "checks": {"original": True},
        "memory_boundary": {"transcript_unchanged": True, "summary_unchanged": True},
    }
    result = {"turns": [deepcopy(turn), deepcopy(turn)]}
    assert (
        assess_trajectory(case, deepcopy(result), faq)[
            "repeated_failed_recommendations"
        ]
        == 1
    )
    case["turns"][1]["feedback_previous_failed"] = False
    assert (
        assess_trajectory(case, deepcopy(result), faq)[
            "repeated_failed_recommendations"
        ]
        == 0
    )


def test_missing_runs_and_estimated_tokens_are_not_success_or_actual_cost():
    """功能：summarize_ablation 保留计划分母；缺少配对不报告提升，估算 usage 不放入真实 Token 栏。"""
    cases, _ = fixtures()
    run = {
        "id": "M01",
        "condition": "on",
        "repetition": 1,
        "automated_pass": True,
        "turns": [
            {
                "automated_pass": True,
                "output": {
                    "elapsed_ms": 10,
                    "usage": {"total_tokens": 20, "estimated_tokens": True},
                },
            }
        ],
    }
    summary = summarize_ablation([run], cases, 3, "live")
    assert summary["groups"]["on"]["planned_runs"] == 18
    assert summary["groups"]["on"]["completed_runs"] == 1
    assert summary["groups"]["off"]["completed_runs"] == 0
    assert summary["groups"]["on"]["actual_input_tokens"] is None
    assert summary["success_delta_percentage_points"] is None


def test_invalid_condition_rejected_before_database_is_created(tmp_path):
    """功能：run_case 在 seed_database 前拒绝拼错的对照组，避免悄悄把 off 当成 on。"""
    cases, _ = fixtures()
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        asyncio.run(run_case(cases[0], str(path), memory_mode="typo"))
    assert not path.exists()
