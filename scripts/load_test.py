"""隔离 HTTP 压测：新建临时库，启动独立服务；只测试业务接口，不调用模型。"""

import argparse
import concurrent.futures
import json
import math
import os
import secrets
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

from react_agent import auth, storage
from scripts.db_admin import copy_database


def percentile(values, fraction):
    """功能：计算最近秩百分位；sorted 排序、ceil 定位，空样本返回 None。"""
    return (
        sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]
        if values
        else None
    )


def exercise(origin, username, password, iterations):
    """功能：一个并发用户通过真实 HTTP 建单/重复确认/查询；Client 保存 Cookie，post/get 调接口，逐步断言业务结果并记录耗时。"""
    samples, errors, tickets = [], [], []
    with httpx.Client(
        base_url=origin, timeout=20, trust_env=False, headers={"Origin": origin}
    ) as client:
        login = client.post(
            "/api/login", json={"user_id": username, "password": password}
        )
        if login.status_code != 200:
            return {
                "samples": [],
                "errors": [f"login:{login.status_code}"],
                "tickets": [],
            }
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        for number in range(iterations):
            started = time.perf_counter()
            try:
                response = client.post("/api/threads")
                response.raise_for_status()
                thread = response.json()["thread_id"]
                key = str(uuid4())
                body = {
                    "action": "create_ticket",
                    "payload": {
                        "product_model": f"LOAD{number}",
                        "issue_description": f"压测设备无法启动 {number}",
                    },
                }
                proposal = client.post(
                    f"/api/threads/{thread}/proposals",
                    json=body,
                    headers={"Idempotency-Key": key},
                )
                proposal.raise_for_status()
                repeated = client.post(
                    f"/api/threads/{thread}/proposals",
                    json=body,
                    headers={"Idempotency-Key": key},
                )
                repeated.raise_for_status()
                assert (
                    repeated.json()["operation_id"] == proposal.json()["operation_id"]
                )
                operation = proposal.json()["operation_id"]
                confirmation = {"thread_id": thread}
                first = client.post(
                    f"/api/operations/{operation}/confirm", json=confirmation
                )
                second = client.post(
                    f"/api/operations/{operation}/confirm", json=confirmation
                )
                first.raise_for_status()
                second.raise_for_status()
                ticket_id = first.json()["ticket"]["ticket_id"]
                assert second.json()["ticket"]["ticket_id"] == ticket_id
                result = client.get(
                    f"/api/tickets/{ticket_id}", params={"thread_id": thread}
                )
                result.raise_for_status()
                assert result.json()["ticket"]["owner_id"] == username
                tickets.append(ticket_id)
            except (httpx.HTTPError, AssertionError, KeyError) as error:
                errors.append(type(error).__name__)
            samples.append((time.perf_counter() - started) * 1000)
    return {"samples": samples, "errors": errors, "tickets": tickets}


def run_load(clients=8, iterations=10):
    """功能：准备隔离数据库并启动 Uvicorn；线程池模拟用户，SQLite 核对唯一写入，copy_database 实际备份恢复，finally 关闭服务。"""
    if not 1 <= clients <= 24 or not 1 <= iterations <= 100:
        raise ValueError("客户端数量限 1–24，每客户端循环限 1–100")
    with tempfile.TemporaryDirectory(prefix="ticket-load-") as directory:
        database = str(Path(directory) / "load.sqlite3")
        password = secrets.token_urlsafe(18)
        auth.create_user("loadadmin", password, "admin", database, bootstrap=True)
        # 复制同一已派生测试密码散列，避免把账号准备耗时混入业务压测。
        with storage.connect(database) as db:
            digest = db.execute(
                "SELECT password_hash FROM users WHERE user_id='loadadmin'"
            ).fetchone()[0]
            for number in range(clients):
                db.execute(
                    "INSERT INTO users VALUES (?,?, 'customer','[]','[]',1,?)",
                    (f"loaduser{number}", digest, storage.now()),
                )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "TICKET_DB_PATH": database,
            "APP_ORIGIN": origin,
            "DEEPSEEK_API_KEY": "",
            "OPENAI_API_KEY": "",
            "LANGSMITH_TRACING": "false",
        }
        with open(Path(directory) / "server.log", "w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "react_agent.api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                with httpx.Client(trust_env=False, timeout=1) as probe:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError("隔离服务启动失败")
                        try:
                            if probe.get(origin + "/health/ready").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise TimeoutError("隔离服务未就绪")
                started = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
                    futures = [
                        pool.submit(
                            exercise, origin, f"loaduser{i}", password, iterations
                        )
                        for i in range(clients)
                    ]
                    outcomes = [future.result() for future in futures]
                elapsed = time.perf_counter() - started
                samples = [value for row in outcomes for value in row["samples"]]
                errors = [value for row in outcomes for value in row["errors"]]
                ticket_ids = [value for row in outcomes for value in row["tickets"]]
                with storage.connect(database) as db:
                    actual = db.execute("SELECT count(*) FROM tickets").fetchone()[0]
                    audits = db.execute(
                        "SELECT count(*) FROM ticket_events WHERE action='create_ticket'"
                    ).fetchone()[0]
                backup = Path(directory) / "snapshot.sqlite3"
                restored = Path(directory) / "restored.sqlite3"
                copy_database(database, backup)
                recovery = copy_database(backup, restored, restore=True)
                with sqlite3.connect(restored) as db:
                    sessions_left = db.execute(
                        "SELECT count(*) FROM login_sessions"
                    ).fetchone()[0]
                expected = clients * iterations
                passed = (
                    not errors
                    and len(samples) == expected
                    and actual == audits == len(set(ticket_ids)) == expected
                    and recovery["tickets"] == expected
                    and sessions_left == 0
                )
                return {
                    "success": passed,
                    "created_at": storage.now(),
                    "clients": clients,
                    "iterations_per_client": iterations,
                    "expected_workflows": expected,
                    "completed_workflows": len(ticket_ids),
                    "errors": errors,
                    "database_tickets": actual,
                    "creation_audits": audits,
                    "elapsed_seconds": round(elapsed, 3),
                    "workflows_per_second": round(len(ticket_ids) / elapsed, 2),
                    "workflow_latency_ms": {
                        "mean": round(statistics.mean(samples), 2) if samples else None,
                        "p50": percentile(samples, 0.5),
                        "p95": percentile(samples, 0.95),
                        "p99": percentile(samples, 0.99),
                    },
                    "restore_verified": recovery["tickets"] == expected
                    and sessions_left == 0,
                    "scope": "本机单进程，临时库；每轮 6 次 HTTP 请求：建会话、提案、重放提案、确认、重复确认、详情。包含本地网络/数据库，不含 LLM。总吞吐计时含并发登录，单轮延迟不含登录。",
                }
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    """功能：解析压测规模并输出报告；run_load 完成隔离演练，write_text 写统计信息，失败以非零状态退出。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--output", default="reports/http-load.json")
    args = parser.parse_args()
    result = run_load(args.clients, args.iterations)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
