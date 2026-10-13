"""隔离数据库和账号，测试绝不写入用户的演示数据。"""

import shutil

import pytest

from react_agent import auth, sessions
from react_agent.context import Context


# 函数说明：account_database
# 功能：调用 create_user 建立一次账号模板；每项测试复制文件，避免重复密码派生的开销。
# 内部调用：
#   - tmp_path_factory.mktemp()：让 pytest 为账号模板创建会话级临时目录。
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - auth.create_user()：事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。
# 装饰器：
#   - @pytest.fixture：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。
@pytest.fixture(scope="session")
def account_database(tmp_path_factory):
    """调用 create_user 建立一次账号模板；每项测试复制文件，避免重复密码派生的开销。"""
    path = str(tmp_path_factory.mktemp("accounts") / "template.db")
    auth.create_user("admin", "test-password", "admin", path, bootstrap=True)
    for user in ("alice", "bob"):
        auth.create_user(user, "test-password", db_path=path)
    auth.create_user(
        "tech",
        "test-password",
        "technician",
        path,
        administrator="admin",
        models=["X100"],
        specialties=["network", "safety"],
    )
    auth.create_user("support", "test-password", "support", path, administrator="admin")
    return path


# 函数说明：app_db
# 功能：复制模板到测试临时目录，不复制任何用户凭据或实际工单。
# 内部调用：
#   - str()：把路径、编号或异常等转换为文本，便于传参、显示或构造标识。
#   - shutil.copyfile()：把测试账号模板复制到当前测试独有的数据库文件，避免修改共享或真实数据。
# 装饰器：
#   - @pytest.fixture：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。
@pytest.fixture
def app_db(tmp_path, account_database):
    """复制模板到测试临时目录，不复制任何用户凭据或实际工单。"""
    path = str(tmp_path / "app.db")
    shutil.copyfile(account_database, path)
    return path


# 函数说明：ctx
# 功能：调用 create_thread 创建客户会话，再由应用构造 Context。
# 内部调用：
#   - sessions.create_thread()：验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。
#   - Context()：创建应用运行上下文，携带经过应用验证的身份、会话、请求、数据库路径和预算；这些不是模型可填的工具参数。
# 装饰器：
#   - @pytest.fixture：把此函数注册为测试夹具；pytest 根据同名参数提供返回值，scope=session 时整个测试会话只准备一次。
@pytest.fixture
def ctx(app_db):
    """调用 create_thread 创建客户会话，再由应用构造 Context。"""
    return Context(
        user_id="alice",
        thread_id=sessions.create_thread("alice", app_db),
        db_path=app_db,
    )


# 函数说明：new_request
# 功能：结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。
# 内部调用：
#   - sessions.active_request()：查找当前会话未完成的请求，供刷新后的重试按钮恢复使用。
#   - sessions.abandon_request()：撤销未运行请求及其待确认操作；活动租约未到期时不允许并发结束。
#   - sessions.begin_request()：在事务中检查会话与未完请求，生成 request_id、更新事实、撤销旧待确认操作并记录用户输入。
def new_request(context, text="请处理我的工单"):
    """结束测试前一轮请求后调用 begin_request，生成真实应用请求编号。"""
    active = sessions.active_request(
        context.thread_id, context.user_id, context.db_path
    )
    if active:
        sessions.abandon_request(active["request_id"], context.user_id, context.db_path)
    context.request_id = sessions.begin_request(
        context.thread_id, context.user_id, text, context.db_path
    )
    return context
