"""演示部署的周期备份进程；先生成可校验快照，再发布成功时间供健康检查读取。"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts.db_admin import copy_database


def backup_once(source, directory):
    """功能：保存一个新的完整快照；copy_database 在线一致备份并校验，replace 原子更新成功标记，uuid4 防止文件重名。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = copy_database(
        source, directory / f"ticket-{stamp}-{uuid4().hex[:8]}.sqlite3"
    )
    marker = directory / ".last-success"
    temporary = directory / f".health-{uuid4().hex}"
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(marker)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def healthy(directory, max_age):
    """功能：检查最近备份是否仍在有效时间内；read_text/loads 读取标记，stat 检查快照和标记时间，不因进程存活就认定备份成功。"""
    try:
        marker = Path(directory) / ".last-success"
        report = json.loads(marker.read_text(encoding="utf-8"))
        return (
            Path(report["path"]).is_file()
            and 0 <= time.time() - marker.stat().st_mtime <= max_age
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main():
    """功能：运行一次备份、周期备份或健康检查；argparse 校验参数，backup_once 执行，healthy 返回退出码，sleep 控制间隔。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--max-age", type=int, default=7500)
    parser.add_argument("--check-health", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 1 or args.max_age < 1:
        parser.error("时间参数必须大于零")
    if args.check_health:
        raise SystemExit(0 if healthy(args.directory, args.max_age) else 1)
    if not args.source:
        parser.error("备份需要 --source")
    while True:
        try:
            print(
                json.dumps(
                    backup_once(args.source, args.directory), ensure_ascii=False
                ),
                flush=True,
            )
        except Exception as error:
            # 不把异常原文或数据库内容写入公开日志；没有新成功标记时健康检查会超时失败。
            print(
                json.dumps({"backup": "failed", "error_type": type(error).__name__}),
                flush=True,
            )
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
