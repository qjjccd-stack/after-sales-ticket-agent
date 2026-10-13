"""快照恢复测试：隔离数据库，不访问用户实际库。"""

import asyncio
import importlib
import os

import pytest
from conftest import new_request
from langchain_core.messages import AIMessage
from test_graph import ScriptedModel, tool_call

from react_agent import actions, auth, sessions, storage
from react_agent.context import Context
from react_agent.service import run_request
from scripts.db_admin import copy_database


def test_snapshot_restores_checkpoints_and_revokes_sessions(ctx, tmp_path, monkeypatch):
    """功能：备份中断后的图状态并恢复到新库；copy_database 撤销登录/释放租约，run_request 真正续跑，验证原库保持失败状态。"""
    token = auth.login(ctx.user_id, "test-password", ctx.db_path)["token"]
    model = ScriptedModel(
        [
            tool_call(
                "create_ticket",
                {"product_model": "X100", "issue_description": "无法联网"},
            ),
            RuntimeError("interruption"),
        ]
    )
    module = importlib.import_module("react_agent.graph")
    monkeypatch.setattr(module, "load_chat_model", lambda _: model)
    new_request(ctx, "X100无法联网，请建单")
    assert not asyncio.run(run_request(ctx.request_id, ctx.user_id, ctx.db_path))[
        "success"
    ]
    # 模拟进程退出时仍持有租约；快照恢复后不应继续等待旧进程。
    sessions.claim_request(ctx.request_id, ctx.user_id, ctx.db_path)
    snapshot, restored = tmp_path / "backup.db", tmp_path / "restored.db"
    copy_database(ctx.db_path, snapshot)
    report = copy_database(snapshot, restored, restore=True)
    assert report["schema_version"] == 4
    assert os.stat(restored).st_mode & 0o777 == 0o600
    assert auth.authenticate(token, str(restored)) is None
    assert auth.authenticate(token, ctx.db_path) is not None
    recovered = sessions.get_request(ctx.request_id, ctx.user_id, str(restored))
    assert recovered["status"] == "failed" and recovered["lease_until"] == 0
    next_model = ScriptedModel([AIMessage(content="请确认")])
    monkeypatch.setattr(module, "load_chat_model", lambda _: next_model)
    outcome = asyncio.run(run_request(ctx.request_id, ctx.user_id, str(restored)))
    assert outcome["success"] and outcome["usage"]["tool_calls"] == 1
    context = Context(
        user_id=ctx.user_id, thread_id=ctx.thread_id, db_path=str(restored)
    )
    operation = actions.pending_actions(context)[0]["operation_id"]
    assert actions.confirm_action(context, operation)["success"]
    assert len(storage.list_tickets(str(restored))) == 1
    assert storage.list_tickets(ctx.db_path) == []


def test_snapshot_refuses_overwrite_and_invalid_source(app_db, tmp_path):
    """功能：防止误覆盖或把损坏文件当快照；copy_database 必须抛错且原目标字节不变。"""
    target = tmp_path / "exists.db"
    target.write_bytes(b"keep-me")
    with pytest.raises(FileExistsError):
        copy_database(app_db, target)
    assert target.read_bytes() == b"keep-me"
    with pytest.raises(FileNotFoundError):
        copy_database(tmp_path / "missing.db", tmp_path / "new.db")
    assert not (tmp_path / "new.db").exists()
