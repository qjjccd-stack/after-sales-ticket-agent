"""本机数据库管理：初始化管理员、在线快照、恢复到新文件；从不覆盖运行库。"""

import argparse
import getpass
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from react_agent import auth, storage


def inspect_database(path):
    """功能：只读检查快照；as_uri/connect 避免意外新建源库，quick_check 校验一致性，SELECT 验证应用表和版本。"""
    path = Path(path).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("数据库完整性检查失败")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            version not in {2, 3, 4}
            or not {"users", "tickets", "requests", "pending_actions"} <= tables
        ):
            raise ValueError("不是受支持的售后数据库快照")
        return {
            "schema_version": version,
            "tickets": db.execute("SELECT count(*) FROM tickets").fetchone()[0],
            "requests": db.execute("SELECT count(*) FROM requests").fetchone()[0],
        }
    finally:
        db.close()


def copy_database(source, destination, *, restore=False):
    """功能：用 SQLite backup API 取得一致快照；mkstemp 建私有临时文件、os.link 原子发布且不覆盖；恢复时撤销会话并释放中断租约。"""
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    inspect_database(source)
    if destination.exists() or source == destination:
        raise FileExistsError("目标必须是不存在的新文件；请勿覆盖正在运行的数据库")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=".ticket-snapshot-", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10)
    copied = sqlite3.connect(temporary)
    try:
        original.backup(copied)
        if restore:
            # 恢复所有业务记录和图检查点，但旧登录凭据不应在恢复环境重新生效。
            with copied:
                copied.execute("DELETE FROM login_sessions")
                copied.execute(
                    "UPDATE requests SET status='failed',lease_until=0,lease_token='' WHERE status='running'"
                )
                if copied.execute("PRAGMA user_version").fetchone()[0] >= 4:
                    copied.execute(
                        "UPDATE model_admissions SET expires_at=0 WHERE state='active'"
                    )
        copied.close()
        info = inspect_database(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.link(temporary, destination)
        return {
            **info,
            "action": "restore" if restore else "backup",
            "path": str(destination),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "created_at": storage.now(),
        }
    finally:
        copied.close()
        original.close()
        temporary.unlink(missing_ok=True)


def manage_account(db_path, user_id, *, password=None):
    """功能：由服务器管理员撤销邀请或重置密码；password_digest 派生新散列，事务内检查最后一个管理员，UPDATE 修改账号并 DELETE 撤销该账号全部登录。"""
    db_path = str(Path(db_path).resolve(strict=True))
    if password is not None and not 8 <= len(password) <= 128:
        raise ValueError("密码需 8–128 位")
    digest = auth.password_digest(password) if password is not None else None
    with storage.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute(
            "SELECT role,active FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if not user:
            raise ValueError("账号不存在")
        if digest is None:
            admins = db.execute(
                "SELECT count(*) FROM users WHERE role='admin' AND active=1"
            ).fetchone()[0]
            if user["role"] == "admin" and user["active"] and admins <= 1:
                raise ValueError("不能停用最后一个有效管理员")
            db.execute("UPDATE users SET active=0 WHERE user_id=?", (user_id,))
        else:
            db.execute(
                "UPDATE users SET password_hash=? WHERE user_id=?", (digest, user_id)
            )
        db.execute("DELETE FROM login_sessions WHERE user_id=?", (user_id,))
    return {
        "success": True,
        "user_id": user_id,
        "action": "reset-password" if digest else "disable-user",
    }


def main():
    """功能：管理命令入口；argparse 读路径，getpass 隐藏密码，create_user 初始化，manage_account 管理邀请，copy_database 执行快照操作。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser(
        "bootstrap", help="首次管理员初始化（密码从终端输入）"
    )
    bootstrap.add_argument("--db", required=True)
    bootstrap.add_argument("--user", required=True)
    for command in ("disable-user", "reset-password"):
        child = commands.add_parser(command)
        child.add_argument("--db", required=True)
        child.add_argument("--user", required=True)
    for command in ("backup", "restore"):
        child = commands.add_parser(command)
        child.add_argument("--source", required=True)
        child.add_argument("--destination", required=True)
    args = parser.parse_args()
    if args.command == "bootstrap":
        password = getpass.getpass("管理员密码（至少 8 位）：")
        if password != getpass.getpass("再次输入密码："):
            parser.error("两次密码不同")
        result = auth.create_user(args.user, password, "admin", args.db, bootstrap=True)
        if not result["success"]:
            parser.error(result["message"])
        print("管理员已创建。请通过工作台登录并添加工作人员或客户。")
    elif args.command in {"disable-user", "reset-password"}:
        password = None
        if args.command == "reset-password":
            password = getpass.getpass("新密码（8–128 位）：")
            if password != getpass.getpass("再次输入密码："):
                parser.error("两次密码不同")
        try:
            result = manage_account(args.db, args.user, password=password)
        except (ValueError, FileNotFoundError) as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(
            json.dumps(
                copy_database(
                    args.source, args.destination, restore=args.command == "restore"
                ),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
