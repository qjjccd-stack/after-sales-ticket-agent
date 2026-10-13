# 售后工单 Agent · v4

基于 LangGraph、FastAPI 和 SQLite 的售后系统，提供同源网页与 HTTP API，保留 Streamlit 本机调试入口。支持多轮故障排查、持久会话、工单全生命周期和人工接管。模型负责选择工具；业务写入必须经过用户确认，最终回复依据实际工具结果生成。

v2 覆盖需求清单中的 **七类、40 项增强**；v3 增加 HTTP 接口、Cookie/CSRF 登录、提交幂等、备份恢复和隔离压测；v4 补上受邀演示需要的持久模型配额、HTTPS 部署配置、周期备份和账号撤销。业务仍是一个 Python 服务和一个 SQLite 数据库；公网部署模板另配 Caddy 入口与备份进程。FAQ 为模拟产品资料，当前采用型号过滤、同义词分类与 BM25。

**准备部署时先读 [受邀演示版部署指南](docs/demo-deployment.md)**。现在没有服务器也可以保留完整部署包；本次尚未上线公网，容器运行和真实 HTTPS 验收仍待目标环境完成。

## 新的 HTTP 工作台

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock.txt -e '.[dev]'
cp -n .env.example .env
# 仅首次、没有任何账号时执行；已有管理员可直接登录。
.venv/bin/python -m scripts.db_admin bootstrap --db data/tickets.sqlite3 --user admin
.venv/bin/python -m uvicorn react_agent.api:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

打开 [HTTP 工作台](http://127.0.0.1:8000/)。需要调整端口时，同时设置 `APP_ORIGIN`。本机安装、接口、Cookie/CSRF 和恢复步骤见 [部署与恢复指南](docs/deployment.md)，本轮证据见 [v4 验收记录](docs/acceptance-v4.md)。无模型密钥也可以用表单处理工单。

新增函数的作用与主要调用写在源码 docstring/注释中；学习索引见 [HTTP 与运维函数讲解](docs/http-functions.md)。

## 先看哪里

- [40 项功能与实现位置](docs/enhancements.md)：逐项对应需求、设计和边界。
- [原业务函数与调用关系](docs/functions.md)：v2 的 169 个函数逐项讲解；HTTP、配额和运维的新函数及修改部分另见 HTTP 与运维函数讲解。
- [工作流程](docs/workflow.md)：对话、确认写入、权限与状态机。
- [验收记录](docs/acceptance.md)：离线与真实模型结果、失败修复记录及证据。
- [任务成功标准与评测集](docs/evaluation.md)：60 个业务场景、历史失败案例、评分依据和离线/真实模型的区别。

建议阅读顺序：`api.py → service.py → graph.py → tools.py → actions.py → storage.py`；再读 `sessions.py`、`knowledge.py`、`auth.py`。网页交互看 `web/app.js`，旧 Streamlit 入口看 `app.py`。权限和业务规则主要在 `actions.py`，不能只读提示词。

v4 的回归、50 场景离线评测、HTTP 并发和备份结果见 [v4 验收记录](docs/acceptance-v4.md)。[v3 验收记录](docs/acceptance-v3.md) 保留历史基线。各版本结果独立解释，不能把旧模型评测当成新版本真实模型验收。2026-10-10 新增的业务记忆对照实验、范围与运行方法见 [评测指南](docs/evaluation.md#结构化业务记忆的对照实验2026-10-10)。

## v2 历史验证结果

2026-10-08，Python 3.12 / macOS：

| 验证 | 结果 | 说明 |
|---|---|---|
| 本地回归测试 | 67 项通过 | 事务、并发、权限、确认绑定、检查点、上下文、页面、评测器 |
| 50 场景离线评测 | 50/50 | 脚本模型故意返回虚假成功，检验执行层 |
| 50 场景真实 DeepSeek 评测 | 50/50，合计 62 轮 | 自主工具选择；确认由测试驱动模拟页面按钮 |
| 数据库事实一致性 | 32/32 | 每条回复与其生成时刻的数据库快照比较 |
| 工具调用合法性 | 62/65 | 包含越权测试的拒绝和一次错误类别参数；不是模型语义正确率 |
| 真实模型 Token | 330,059 | 服务端 usage；本轮无估算，未配置单价所以金额未知 |

这些数字覆盖 v2 固定用例和当时源码，不代表任意对话都能成功，也不是 v3 的重新付费模型验收。真实报告保留失败版本，报告含源文件 SHA256。评测中的最终业务回答经过确定性渲染，不能把结果写成“原始模型回答 100% 正确”。

## 本机调试入口（Streamlit）

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock.txt -e '.[dev]'
# 仅在没有 .env 时复制，已有配置不要覆盖
cp -n .env.example .env
.venv/bin/streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

打开 [本机页面](http://127.0.0.1:8501/)。首次运行在页面创建管理员账号，再在“账号管理”中添加维修人员、客服或客户。也可退出后自行注册客户账号。没有预设生产密码。

`.env` 中设置 `DEEPSEEK_API_KEY`，默认 `MODEL=deepseek/deepseek-chat`。未配置密钥时仍能使用工单表单、查询、详情和确认；聊天入口禁用。修改环境配置后重启进程。环境变量优先于 `.env`。

默认数据库为 `data/tickets.sqlite3`；`TICKET_DB_PATH` 可改为隔离路径，相对路径以项目根目录为基准。退出登录不会删除对话或工单。首次连接会自动迁移旧表，保留原编号和内容；历史无归属工单标为 `legacy`，只向工作人员展示。

可选配置：`MODEL=openai/模型名`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 使用兼容服务，需要支持工具调用；当前验收使用 DeepSeek。设置 `INPUT_PRICE_PER_MILLION` 与 `OUTPUT_PRICE_PER_MILLION` 后可以显示估算金额，两项必须使用同一币种。

## 演示完整流程

1. 管理员添加维修账号，为其配置 X100 和 network 专长；创建或注册客户账号。
2. 客户输入“我的 X100 无法联网”，查看带 FAQ 编号与来源的逐步排查，反馈“已经试过，还是不行”。
3. 输入“帮我创建工单”。此时只有确认卡片，数据库中还没有新工单。核对型号、描述、分派和相似单提示，再点“确认创建工单”。
4. 刷新页面，继续问“刚才那个工单什么状态”；也可到工作台查看详情和处理记录。
5. 切换到被分派的维修账号，将“待处理 → 处理中 → 待用户确认”，每次都核对卡片并确认。
6. 客户确认修复后进入“已解决”，随后可关闭；若未修好，可将“待用户确认”退回“处理中”。

工作台也能直接填写、补充、取消、分派、调整优先级和转人工，不依赖模型连接。客服和管理员可查看所有工单，客户只能查看自己的工单；维修状态更新由被分派的维修人员或管理员执行。

## 为什么需要多个 ID

| ID | 对应什么 | 生命周期 |
|---|---|---|
| `thread_id` | 一段属于特定账号的持续对话 | 多轮消息、刷新与重启后保留 |
| `request_id` | 一次用户消息或表单提交 | 原请求重试复用；新提交生成新值 |
| `operation_id` | 一张冻结参数的确认卡片 | 绑定用户、会话、请求、动作、参数、版本和有效期 |
| `ticket_id` | 数据库里的售后工单 | 例如 T0001，跨会话查询 |

模型工具参数不包含用户身份、角色、请求编号或 `confirmed`。模型只能提出操作；`confirm_action` 不在模型工具列表中。确认有效期 15 分钟，新消息撤销旧待确认操作，工单版本改变时需重新核对。并发重复确认只执行一次。

## 运行检查

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python scripts/evaluate.py --mode offline
# 只看新增挑战，或重复运行检查稳定性
.venv/bin/python scripts/evaluate.py --mode offline --split challenge --repeat 2
# 以下命令会调用配置的真实模型并产生用量；每个场景使用隔离临时库
.venv/bin/python scripts/evaluate.py --mode live --output reports/my-live-run.json
# 单独检查或限制并发
.venv/bin/python scripts/evaluate.py --mode live --case 31,34,46 --concurrency 2 --output reports/my-regression.json
```

`evaluate.py` 默认是 **offline**，不会调用模型。报告保留输入、工具参数、返回值、确认前后快照、最终文本、Token、耗时与源文件指纹。0 表示自动通过，1 表示失败，2 表示缺密钥未运行。`human_review=pending` 不表示用户已经人工签字。

当前契约包含 50 个强化回归场景和 10 个新增挑战场景，按确认结果、数据库、审计、目标编号和记忆评分；不靠回答看起来像成功。新增评测器负例检查可防“什么也没做但初始字段碰巧正确”等假通过。60 场景全量契约仍只完成离线验收，不能沿用历史 50/50 的真实模型成绩。

业务记忆的独立真实模型对照已完成：6 个固定场景，两组各重复 3 次；开启组 18/18，关闭跨轮结构化记忆组 9/18，重复失败建议分别为 0 和 22 次。开启组 Token 增加约 2.9%，没有据此宣称节省成本。实验只量化当前组件在固定样本中的贡献，范围、失败轨迹和复跑方法见 [评测指南](docs/evaluation.md#结构化业务记忆的对照实验2026-10-10)。本轮 117 项自动化测试及原 60 场景离线回归均通过。

仓库包含已检查的 JSON 评测报告，便于核对实验条件和失败记录；`.env`、运行数据库、虚拟环境、备份及简历输出均被 Git 忽略。新增报告提交前应重新检查是否含有真实用户信息或密钥。

本次首次上传不包含 GitHub Actions 工作流；测试和部署可按上面的命令手动运行。

## 当前边界

- HTTP 网页使用 HttpOnly/SameSite Cookie、CSRF 与 Origin 检查；旧 URL 令牌入口已去除。当前仍缺少公网运行、统一身份认证、多租户隔离和长期运维验证，不能据此宣称企业生产就绪。
- HTTP 请求显式执行/重试，没有后台任务队列；SQLite 单实例。容器与 CI 配置已提供，本机没有 Docker，因此未完成容器构建验证。
- 结构化记忆采用明确规则和带原文证据的工具；历史摘要是有界的原文摘录，不是完整语义记忆。复杂多设备切换和模糊指代可能需要追问。
- 4 条模拟 FAQ 只覆盖部分故障。没有资料就提示补充信息或申请售后；BM25 不是向量 RAG。
- 人工接管是工单标记和工作台队列，未连接真实客服平台，也不会发送消息给工作人员。
- 模型调用、工具次数、输出长度有界；Token 输入预检是估算，服务端实际 usage 用于累计，不能当成计费硬上限。
- v4 HTTP 门禁默认全站并发 2、每账号并发 1、每账号每分钟 6 次执行，日预算按 UTC 计数且持久化；超时或未知结果保守保留预留。修改限额后需重启/重新创建应用；备份卷需要自行配置异机保存和空间管理。

## 上游归属

起点是 [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent) 的快照 `e5bda14b7a5efdeb6f9367a9e4379242ae484f01`，保留 MIT [LICENSE](LICENSE)。v2 已重构图、状态、工具执行与应用逻辑，不再与上游执行逻辑一致。当前没有网页搜索、向量检索或多 Agent。SQLite 检查点依赖可能安装 sqlite-vec，但本项目未使用它做检索。
