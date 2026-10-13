"""部署运维验证；所有账号、数据库和备份均位于 pytest 临时目录。"""

import os
import subprocess
import sys
import time

import pytest

from react_agent import auth, quotas, sessions, storage
from scripts.backup_worker import backup_once, healthy
from scripts.db_admin import copy_database, manage_account


def test_backup_worker_checks_snapshot_age_and_failure(app_db, tmp_path, monkeypatch):
    """功能：验证成功后发布标记、过期后不健康、失败不冒充成功；backup_once/healthy 执行真实快照，utime 模拟旧备份。"""
    directory = tmp_path / "snapshots"
    assert not healthy(directory, 60)
    report = backup_once(app_db, directory)
    assert report["schema_version"] == 4 and healthy(directory, 60)
    marker = directory / ".last-success"
    old = marker.read_bytes()
    with pytest.raises(FileNotFoundError):
        backup_once(tmp_path / "missing.db", directory)
    assert marker.read_bytes() == old
    os.utime(marker, (time.time() - 120, time.time() - 120))
    assert not healthy(directory, 60)


def test_backup_worker_command_runs_from_project(app_db, tmp_path):
    """功能：子进程执行与容器相同的模块入口，避免导入路径只在 pytest 有效；subprocess.run 验证一次备份和健康检查退出码。"""
    directory = str(tmp_path / "cli-backups")
    base = [sys.executable, "-m", "scripts.backup_worker", "--directory", directory]
    done = subprocess.run(
        base + ["--source", app_db, "--once"],
        cwd=storage.ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert done.returncode == 0, done.stderr
    check = subprocess.run(
        base + ["--check-health"], cwd=storage.ROOT, capture_output=True, timeout=15
    )
    assert check.returncode == 0


def test_restore_releases_model_seats_and_retains_budget(app_db, tmp_path):
    """功能：恢复时释放旧进程的席位并保留未知用量；copy_database 生成新库，overview 检查计数，原库席位保持不变。"""
    rid = sessions.begin_request(
        sessions.create_thread("alice", app_db), "alice", "测试请求", app_db
    )
    policy = quotas.DemoLimits()
    quotas.acquire(policy, "alice", rid, app_db, 16000, 160)
    restored = str(tmp_path / "restored.db")
    copy_database(app_db, restored, restore=True)
    info = quotas.overview(policy, restored)
    assert info["active"] == 0 and info["charged_or_reserved_tokens"] == 16000
    assert quotas.overview(policy, app_db)["active"] == 1


def test_schema_three_upgrade_preserves_existing_records(app_db):
    """功能：模拟 v3 库升级；execute 移除 v4 新表并标记旧版本，connect 重建新表，断言原会话和账号仍存在。"""
    thread = sessions.create_thread("alice", app_db)
    with storage.connect(app_db) as db:
        db.execute("DROP TABLE model_admissions")
        db.execute("PRAGMA user_version=3")
    with storage.connect(app_db) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM model_admissions").fetchone()[0] == 0
    assert sessions.get_thread(thread, "alice", app_db)
    assert auth.get_user("alice", app_db)


def test_password_reset_and_invitation_revocation(app_db):
    """功能：重置密码立即撤销旧登录，停用账号阻止登录和取身份；manage_account 修改真实库，authenticate/login 核验边界。"""
    token = auth.login("alice", "test-password", app_db)["token"]
    assert manage_account(app_db, "alice", password="new-test-password")["success"]
    assert auth.authenticate(token, app_db) is None
    assert not auth.login("alice", "test-password", app_db)["success"]
    fresh = auth.login("alice", "new-test-password", app_db)
    assert fresh["success"]
    manage_account(app_db, "alice")
    assert auth.authenticate(fresh["token"], app_db) is None
    assert auth.get_user("alice", app_db) is None
    assert not auth.login("alice", "new-test-password", app_db)["success"]
    with pytest.raises(ValueError, match="最后一个"):
        manage_account(app_db, "admin")
    assert auth.get_user("admin", app_db)
