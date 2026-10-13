"""结构化业务记忆消融：固定场景，交替运行开启/跨轮清空两组；默认离线，不把脚本结果当成模型效果。"""

import argparse
import asyncio
import hashlib
import importlib
import json
import math
import os
import statistics
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from react_agent import storage
from react_agent.context import Context
from react_agent.evaluation import validate_cases
from scripts.evaluate import run_case


def validate_ablation_cases(cases):
    """功能：校验消融专用反馈标记，再调用 validate_cases 校验原业务契约；过滤只发生在副本，不修改冻结样本。"""
    extra = {"feedback_previous_failed", "require_recommendation", "episode"}
    for case in cases:
        for turn in case["turns"]:
            for key in extra - {"episode"}:
                if key in turn and not isinstance(turn[key], bool):
                    raise ValueError(f"{key} 必须为布尔值")
            if set(turn["expect"]) & {
                "memory",
                "tried_count_min",
                "diagnosis_exhausted",
            }:
                raise ValueError("消融评分不能断言内部记忆字段")
    validate_cases(
        [
            {
                **case,
                "turns": [
                    {key: value for key, value in turn.items() if key not in extra}
                    for turn in case["turns"]
                ],
            }
            for case in cases
        ]
    )


def assess_trajectory(case, result, faq):
    """功能：从实际可见回复识别推荐项并查重复；遍历 FAQ 文本匹配步骤，使用预先标注的失败反馈更新集合，不以 memory 是否存在评分。"""
    failed, previous, episode = set(), None, None
    repeated = recommendations = feedback_turns = 0
    for definition, turn in zip(case["turns"], result["turns"], strict=False):
        current_episode = definition.get("episode", "default")
        if current_episode != episode:
            failed, previous, episode = set(), None, current_episode
        if definition.get("feedback_previous_failed"):
            feedback_turns += 1
            if previous:
                failed.add(previous)
        answer = turn["output"]["answer"]
        shown = [
            step["id"]
            for entry in faq
            for step in entry["steps"]
            if answer.startswith("请先尝试：")
            and step["text"] in answer
            and f"来源：{entry['id']}" in answer
        ]
        duplicate = any(step in failed for step in shown)
        repeated += int(duplicate)
        recommendations += len(shown)
        turn["recommended_steps"] = shown
        turn["failed_steps_before_reply"] = sorted(failed)
        turn["repeated_failed_recommendation"] = duplicate
        if case.get("require_no_repeated_failed_steps"):
            turn["checks"]["no_repeated_failed_steps"] = not duplicate
        if definition.get("require_recommendation"):
            turn["checks"]["one_grounded_recommendation"] = len(shown) == 1
        boundary = turn.get("memory_boundary", {})
        turn["checks"]["history_preserved_at_boundary"] = bool(boundary) and all(
            boundary.get(key) for key in ("transcript_unchanged", "summary_unchanged")
        )
        turn["automated_pass"] = all(turn["checks"].values())
        turn["failed_checks"] = [
            key for key, value in turn["checks"].items() if not value
        ]
        # “这个步骤试过了”只绑定上一条真正展示的建议，不能绑定更早的建议。
        previous = shown[-1] if shown else None
    result["repeated_failed_recommendations"] = repeated
    result["recommendations"] = recommendations
    result["feedback_turns"] = feedback_turns
    result["automated_pass"] = len(result["turns"]) == len(case["turns"]) and all(
        turn["automated_pass"] for turn in result["turns"]
    )
    return result


def summarize_ablation(results, cases, repeat, mode):
    """功能：按预定分母汇总成功、重复推荐、真实用量和配对差异；sum/mean 统计，缺失运行不删除，离线或估算 Token 不冒充计费值。"""
    planned = len(cases) * repeat
    planned_turns = sum(len(case["turns"]) for case in cases) * repeat
    groups = {}
    for condition in ("on", "off"):
        runs = [item for item in results if item["condition"] == condition]
        turns = [turn for run in runs for turn in run["turns"]]
        usages = [turn["output"].get("usage", {}) for turn in turns]
        estimated = sum(
            not usage or usage.get("estimated_tokens", True) for usage in usages
        )
        latencies = sorted(turn["output"]["elapsed_ms"] for turn in turns)
        groups[condition] = {
            "passed": sum(run["automated_pass"] for run in runs),
            "planned_runs": planned,
            "completed_runs": len(runs),
            "planned_turns": planned_turns,
            "completed_turns": len(turns),
            "passed_turns": sum(turn["automated_pass"] for turn in turns),
            "runner_errors": sum(bool(run.get("error_code")) for run in runs),
            "all_repeats_passed_cases": sum(
                len(selected := [run for run in runs if run["id"] == case["id"]])
                == repeat
                and all(run["automated_pass"] for run in selected)
                for case in cases
            ),
            "distinct_cases": len(cases),
            "repeated_failed_recommendations": sum(
                run.get("repeated_failed_recommendations", 0) for run in runs
            ),
            "recommendations": sum(run.get("recommendations", 0) for run in runs),
            "feedback_turns": sum(run.get("feedback_turns", 0) for run in runs),
            "estimated_usage_turns": estimated,
            "recorded_total_tokens": sum(
                usage.get("total_tokens", 0) for usage in usages
            ),
            "actual_input_tokens": sum(usage.get("input_tokens", 0) for usage in usages)
            if mode == "live" and usages and not estimated
            else None,
            "actual_output_tokens": sum(
                usage.get("output_tokens", 0) for usage in usages
            )
            if mode == "live" and usages and not estimated
            else None,
            "mean_turn_ms": round(statistics.mean(latencies), 2) if latencies else None,
            "p95_turn_ms": latencies[math.ceil(len(latencies) * 0.95) - 1]
            if latencies
            else None,
        }
    pairs = []
    for case in cases:
        for repetition in range(1, repeat + 1):
            pair = {
                item["condition"]: item
                for item in results
                if item["id"] == case["id"] and item["repetition"] == repetition
            }
            pairs.append(
                {
                    "id": case["id"],
                    "repetition": repetition,
                    "on": pair["on"]["automated_pass"] if "on" in pair else None,
                    "off": pair["off"]["automated_pass"] if "off" in pair else None,
                }
            )
    complete = all(pair["on"] is not None and pair["off"] is not None for pair in pairs)
    return {
        "groups": groups,
        "paired_outcomes": pairs,
        "success_delta_percentage_points": round(
            100 * (groups["on"]["passed"] - groups["off"]["passed"]) / planned, 2
        )
        if complete
        else None,
        "on_only_passed_pairs": sum(
            pair["on"] is True and pair["off"] is False for pair in pairs
        ),
        "off_only_passed_pairs": sum(
            pair["off"] is True and pair["on"] is False for pair in pairs
        ),
        "both_passed_pairs": sum(
            pair["on"] is True and pair["off"] is True for pair in pairs
        ),
        "both_failed_pairs": sum(
            pair["on"] is False and pair["off"] is False for pair in pairs
        ),
    }


def save_report(path, report, cases, repeat, mode):
    """功能：增量保存证据；summarize_ablation 刷新统计，write_text 写临时 JSON，replace 原子替换，避免中断留下半个文件。"""
    report["metrics"] = summarize_ablation(report["runs"], cases, repeat, mode)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def experiment_hashes():
    """功能：固定实验来源；glob 枚举实际源码、用例和 FAQ，sha256 对字节计算指纹，不读取环境密钥。"""
    paths = [
        *storage.ROOT.glob("src/react_agent/*.py"),
        storage.ROOT / "scripts/evaluate.py",
        storage.ROOT / "scripts/evaluate_memory.py",
        storage.ROOT / "data/memory_ablation_cases.json",
        storage.ROOT / "data/faq.json",
    ]
    return {
        str(path.relative_to(storage.ROOT)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(paths)
    }


async def main():
    """功能：校验固定用例并交替运行两组；TemporaryDirectory 隔离业务库，run_case 执行业务，assess_trajectory 评分，finally 恢复离线替身。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--case", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--max-total-tokens", type=int, default=1200000)
    args = parser.parse_args()
    if args.max_total_tokens < 16000:
        parser.error("总预算至少为 16000 Token")
    load_dotenv(storage.ROOT / ".env")
    cases = json.loads((storage.ROOT / "data/memory_ablation_cases.json").read_text())
    validate_ablation_cases(cases)
    if args.case:
        requested = set(args.case.split(","))
        if requested - {case["id"] for case in cases}:
            parser.error("存在未知场景编号")
        cases = [case for case in cases if case["id"] in requested]
    # 不允许用“记忆字段存在”作为成功标准，否则关闭组会被定义成必败。
    if any(
        set(turn["expect"]) & {"memory", "tried_count_min", "diagnosis_exhausted"}
        for case in cases
        for turn in case["turns"]
    ):
        parser.error("消融评分只允许可见业务结果，不能断言内部记忆字段")
    faq = json.loads((storage.ROOT / "data/faq.json").read_text())
    model = Context().model
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = Path(args.output or f"reports/memory-ablation-{args.mode}-{stamp}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        parser.error("报告已存在，请换一个路径以保留原始证据")
    report = {
        "time": datetime.now(UTC).isoformat(),
        "status": "running",
        "mode": args.mode,
        "model": model if args.mode == "live" else "scripted-offline",
        "contract_version": "memory-ablation-1",
        "repeat": args.repeat,
        "planned_cases": len(cases),
        "planned_runs": len(cases) * args.repeat * 2,
        "planned_turns": sum(len(case["turns"]) for case in cases) * args.repeat * 2,
        "max_total_tokens": args.max_total_tokens,
        "human_review": "pending",
        "source_sha256": experiment_hashes(),
        "protocol": {
            "on": "保留跨轮 TicketContext，当前生产逻辑",
            "off": "每个新用户请求前清空 TicketContext；当前轮仍可提取/重建事实",
            "fixed": [
                "模型及 temperature=0",
                "每个场景的用户输入和确认脚本",
                "系统提示词",
                "最近六轮/字符上限",
                "历史摘要算法",
                "工具及可信回复渲染",
                "角色、事务、确认、幂等",
                "逐轮评分规则",
            ],
            "order": "按场景和重复序号交替 on/off；串行避免并发竞争影响",
            "scope": "端到端结构化记忆组件贡献，包含模型上下文、工具过滤和应用回复；不等于模型自身记忆能力",
            "baseline": "保留完整聊天存储、相同裁剪规则、摘要和检查点；不清除消息历史，允许模型从可见历史重建本轮事实",
            "limitations": [
                "六个公开合成场景，非盲测或线上流量",
                "重复运行不是新增独立样本",
                "FAQ 推荐项含一个售后升级项",
                "离线调用由脚本预设，只验证执行层",
                "Token 预算在场景边界按剩余最坏请求预算预检，非账单硬上限",
            ],
        },
        "runs": [],
    }
    save_report(output, report, cases, args.repeat, args.mode)
    key = "DEEPSEEK_API_KEY" if model.startswith("deepseek/") else "OPENAI_API_KEY"
    if args.mode == "live" and not os.getenv(key, "").strip():
        report["status"] = "not_run_missing_credentials"
        save_report(output, report, cases, args.repeat, args.mode)
        return 2
    graph_module = importlib.import_module("react_agent.graph")
    original, model_map = graph_module.load_chat_model, {}
    if args.mode == "offline":
        graph_module.load_chat_model = lambda name: model_map[name]
    try:
        with tempfile.TemporaryDirectory(prefix="ticket-memory-ablation-") as folder:
            for repetition in range(1, args.repeat + 1):
                for index, case in enumerate(cases):
                    order = ("on", "off") if (repetition + index) % 2 else ("off", "on")
                    for condition in order:
                        used = sum(
                            turn["output"].get("usage", {}).get("total_tokens", 0)
                            for run in report["runs"]
                            for turn in run["turns"]
                        )
                        if (
                            args.mode == "live"
                            and used + len(case["turns"]) * 16000
                            > args.max_total_tokens
                        ):
                            report["status"] = "stopped_budget"
                            save_report(output, report, cases, args.repeat, args.mode)
                            return 2
                        try:
                            result = await run_case(
                                case,
                                str(
                                    Path(folder)
                                    / f"{case['id']}-{repetition}-{condition}.db"
                                ),
                                args.mode,
                                model_map,
                                repetition,
                                memory_mode=condition,
                                request_limits={"model": model},
                            )
                            result = assess_trajectory(case, result, faq)
                        except Exception as error:
                            result = {
                                "id": case["id"],
                                "name": case["name"],
                                "repetition": repetition,
                                "turns": [],
                                "automated_pass": False,
                                "error_code": type(error).__name__,
                            }
                        result["condition"] = condition
                        report["runs"].append(result)
                        save_report(output, report, cases, args.repeat, args.mode)
                        print(
                            f"{case['id']} run={repetition} memory={condition}: {'PASS' if result['automated_pass'] else 'FAIL'} repeats={result.get('repeated_failed_recommendations', 0)}",
                            flush=True,
                        )
                        # 连通性失败不是记忆差异；保留该次证据并停止，避免批量消耗失败重试。
                        infra = {
                            "APIConnectionError",
                            "OpenAIConnectionError",
                            "AuthenticationError",
                            "OpenAIAuthenticationError",
                            "PermissionDeniedError",
                            "RateLimitError",
                            "OpenAIRateLimitError",
                            "APITimeoutError",
                            "OpenAITimeoutError",
                        }
                        if any(
                            turn["output"].get("error_code") in infra
                            for turn in result["turns"]
                        ):
                            report["status"] = "stopped_provider_error"
                            save_report(output, report, cases, args.repeat, args.mode)
                            return 2
        report["status"] = "completed"
        save_report(output, report, cases, args.repeat, args.mode)
        print(json.dumps(report["metrics"]["groups"], ensure_ascii=False), flush=True)
        return 0
    finally:
        graph_module.load_chat_model = original


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
