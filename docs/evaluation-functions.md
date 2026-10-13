# 评测函数与内部调用说明

更新时间：2026-10-10。先读数据集，再沿 run_case → check_turn → summarize 阅读；契约函数解释证据如何转为分数。以下均对应当前源码；旧业务层的细粒度说明仍见 [原业务函数讲解](functions.md)。

离线模式使用固定工具请求，真实模式由模型自主选择；确认由评测驱动器模拟用户按钮。新增和修改函数均列出功能与内部调用。

## src/react_agent/evaluation.py

### `validate_cases()`

[查看源码](../src/react_agent/evaluation.py#L103)

功能：在付费调用前检查数据集契约；set 检查重复编号和未知断言，逐轮验证确认方式、角色与目标，避免拼错字段被静默忽略。

| 调用 | 作用 |
|---|---|
| `set` | 计算去重集合或检查未知字段。 |
| `case.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `isinstance` | 校验输入的实际类型。 |
| `identifier.isalnum` | 检查场景编号只含字母和数字，避免重名或非法临时文件路径。 |
| `ValueError` | 拒绝不符合业务或配置规则的输入。 |
| `identifiers.add` | 把已检查编号放进集合，用于发现重复编号。 |
| `turn.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `type` | 读取异常类型名称，避免输出异常中的私人文本。 |
| `expected.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |

### `assess_contract()`

[查看源码](../src/react_agent/evaluation.py#L171)

功能：用快照、冻结参数、成功确认及本轮审计判定任务；any/all 检查证据，按 ticket_id 比较目标，禁止仅凭最终字段碰巧相等就通过。

| 调用 | 作用 |
|---|---|
| `expected.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `len` | 检查数量或长度限制。 |
| `any` | 判断是否存在非法字段。 |
| `outcome.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `all` | 要求所有证据或所有重复运行都满足条件，任何一项失败都不能算通过。 |
| `{**item.get('payload', {}), 'action': item.get('action')}.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `item.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `fields.items` | 遍历字段与值。 |
| `entry.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `ticket.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `memory.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |

### `classify_failures()`

[查看源码](../src/react_agent/evaluation.py#L256)

功能：把失败断言映射成可分析的失败类型；FAILURE_RULES 提供严重级别，未细分断言归为业务目标未达到，不武断推断模型根因。

| 调用 | 作用 |
|---|---|
| `checks.items` | 遍历字段与值。 |
| `FAILURE_RULES.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `failures.append` | 收集输出或测试统计。 |

### `confirmation_facts()`

[查看源码](../src/react_agent/evaluation.py#L270)

功能：提取确认结果的业务事实；get 读取动作、成功标记和工单，统一可选状态字段；不比较 reused 等重复请求提示元数据。

| 调用 | 作用 |
|---|---|
| `outcome.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `ticket.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |

### `grouped_metrics()`

[查看源码](../src/react_agent/evaluation.py#L282)

功能：按类别/分组统计，并列出失败及多次运行稳定性；Counter 统计失败标签，set 汇总不同场景编号，保留分母而不抹掉异常用例。

| 调用 | 作用 |
|---|---|
| `sorted` | 排序耗时样本。 |
| `case.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `sum` | 累加通过数、Token 用量或失败次数，统计时保留分母。 |
| `len` | 检查数量或长度限制。 |
| `turn.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `dict` | 复制客户端 Cookie 映射，模拟浏览器在服务重启后仍保留原登录。 |
| `Counter` | 按失败标签计数，发现哪些失败最集中。 |
| `bool` | 转换为明确布尔值。 |
| `all` | 要求所有证据或所有重复运行都满足条件，任何一项失败都不能算通过。 |

## scripts/evaluate.py

### `OfflineModel.__init__()`

[查看源码](../scripts/evaluate.py#L40)

根据场景定义构造响应队列；最终故意虚构状态以检验可信回复。

| 调用 | 作用 |
|---|---|
| `messages.append` | 收集输出或测试统计。 |
| `AIMessage` | 构造模拟模型回复或工具调用的 LangChain 消息。 |
| `enumerate` | 遍历时携带序号，为工具请求、轮次或种子工单生成不同编号。 |
| `iter` | 把固定响应队列转成迭代器，让离线模型逐条输出。 |

### `OfflineModel.bind_tools()`

[查看源码](../scripts/evaluate.py#L60)

返回测试模型本身；真实工具仍由图执行器调用。

### `OfflineModel.ainvoke()`

[查看源码](../scripts/evaluate.py#L68)

返回下一条固定消息，序列耗尽表明测试模型和执行流程不符。

| 调用 | 作用 |
|---|---|
| `next` | 从迭代器取下一项，或按编号找到目标工单/场景。 |

### `answer_consistent()`

[查看源码](../scripts/evaluate.py#L82)

功能：按句核对明确状态及建单编号；split/finditer 提取可识别陈述，数据库和成功确认提供证据，其他句子的否定词不能掩盖错误。

| 调用 | 作用 |
|---|---|
| `re.split` | 按句号、问号、感叹号或换行划分业务陈述，避免跨句否定词干扰。 |
| `list` | 展开迭代结果。 |
| `re.finditer` | 逐条提取明确的工单状态陈述，保留每条在句子中的位置。 |
| `max` | 取得最大值或约束计数下限。 |
| `match.start` | 返回匹配文本的开始位置，用于仅检查当前陈述附近的否定词。 |
| `match.end` | 返回匹配文本的结束位置，限定当前陈述。 |
| `re.search` | 查找明确的状态、创建成功或局部否定表达。 |
| `claims.append` | 收集输出或测试统计。 |
| `match.groups` | 取正则捕获的工单编号与状态。 |
| `creation.start` | 返回匹配文本的开始位置，用于仅检查当前陈述附近的否定词。 |
| `item.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `set` | 计算去重集合或检查未知字段。 |
| `re.findall` | 提取当前建单陈述中出现的所有工单编号。 |
| `records.keys` | 取得数据库快照中的真实工单编号集合。 |

### `check_turn()`

[查看源码](../scripts/evaluate.py#L138)

功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。

| 调用 | 作用 |
|---|---|
| `len` | 检查数量或长度限制。 |
| `expected.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `bool` | 转换为明确布尔值。 |
| `answer.strip` | 删除首尾空白，识别空消息或空配置。 |
| `all` | 要求所有证据或所有重复运行都满足条件，任何一项失败都不能算通过。 |
| `answer_consistent` | 功能：按句核对明确状态及建单编号；split/finditer 提取可识别陈述，数据库和成功确认提供证据，其他句子的否定词不能掩盖错误。 |
| `item.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `any` | 判断是否存在非法字段。 |
| `outcome.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `next` | 从迭代器取下一项，或按编号找到目标工单/场景。 |
| `term.casefold` | 统一中英文大小写，接受 Wi-Fi 等故障描述的等义词。 |
| `target['issue_description'].casefold` | 统一中英文大小写，接受 Wi-Fi 等故障描述的等义词。 |
| `checks.update` | 合并基础断言与业务契约断言，不丢弃原有检查结果。 |
| `assess_contract` | 功能：用快照、冻结参数、成功确认及本轮审计判定任务；any/all 检查证据，按 ticket_id 比较目标，禁止仅凭最终字段碰巧相等就通过。 |
| `classify_failures` | 功能：把失败断言映射成可分析的失败类型；FAILURE_RULES 提供严重级别，未细分断言归为业务目标未达到，不武断推断模型根因。 |
| `checks.values` | 遍历字典中的所有值。 |

### `seed_database()`

[查看源码](../scripts/evaluate.py#L281)

功能：准备隔离前置条件；create_user 建测试账号，enumerate/insert_ticket 准备一张或多张种子工单，SQL 设置初始状态；种子不计为 Agent 完成。

| 调用 | 作用 |
|---|---|
| `auth.create_user` | 事务内创建账号；首次管理员需 bootstrap，后续提权需数据库中的管理员，普通注册仅客户。 |
| `case.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `enumerate` | 遍历时携带序号，为工具请求、轮次或种子工单生成不同编号。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `storage.insert_ticket` | 可信事务内建单：SELECT 去重，INSERT 后重新查询，并调用 record_change。 |
| `seed.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |

### `run_case()`

[查看源码](../scripts/evaluate.py#L336)

功能：驱动完整业务场景；seed_database 准备前置，run_request 执行/重放，confirm_action 模拟用户点击，check_turn 评分，SQLite 快照和审计保存证据。

消融实验额外传入 `memory_mode` 和 `request_limits`。默认不传，原回归行为不变；`off` 在新请求之前调用 `sessions.save_memory(..., {})` 清空跨轮业务字段，并用两次 `sessions.get_thread` 检查聊天记录、摘要没有变化。这个开关只属于隔离评测入口，没有开放成网页或模型参数。

| 调用 | 作用 |
|---|---|
| `asyncio.to_thread` | 在线程中准备测试数据库，避免密码计算/同步 SQLite 阻塞异步调度。 |
| `case.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `sessions.create_thread` | 验证用户后由 uuid4 生成会话 ID，调用 INSERT 创建独立持久记录。 |
| `Context` | 构造服务端运行上下文，包含真实用户、会话、请求和数据库位置。 |
| `enumerate` | 遍历时携带序号，为工具请求、轮次或种子工单生成不同编号。 |
| `storage.list_tickets` | 可信内部全量读取；调用 connect/SELECT。页面使用带权限的 actions.search_tickets。 |
| `storage.connect` | 调用 database_path/migrate 打开数据库；with db 管理提交/回滚，finally 关闭。 |
| `db.execute('SELECT coalesce(max(event_id),0) FROM ticket_events').fetchone` | 读取一行数据库结果。 |
| `db.execute` | 执行参数化 SQL 或事务指令；值通过占位符绑定。 |
| `sessions.begin_request` | 事务内保存请求；SELECT 复用 HTTP 幂等键，参数冲突拒绝；display_text 仅由应用传入，用于把表单记录显示成人类可读内容。 |
| `OfflineModel` | 建立固定工具请求加虚假成功文本的模拟模型，用来检验执行层与可信回复。 |
| `run_request` | claim_request 获取租约，用 aget_state 判断是否恢复检查点，astream 收集输出，finish_request 保存结果。 |
| `turn.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `sessions.timeline` | 先检查会话归属，再查询执行事件；json.loads 还原参数和真实结果。 |
| `actions.pending_actions` | 检查身份后列出本会话未过期提案；页面只展示这里返回的服务器保存参数。 |
| `confirmations.append` | 收集输出或测试统计。 |
| `actions.confirm_action` | 页面专用入口：事务内复核身份/参数摘要/有效期/版本/权限，写库、审计、保存结果一起提交。无模型工具暴露。 |
| `reply_snapshots.append` | 收集输出或测试统计。 |
| `actions.render_result` | 完全由可信结构化结果生成业务确认；不使用模型文字判断创建或状态更新是否成功。 |
| `dict` | 复制客户端 Cookie 映射，模拟浏览器在服务重启后仍保留原登录。 |
| `sessions.get_thread` | 按会话和用户共同查询，调用 json.loads 还原；别人的会话不可读取。 |
| `'\n'.join` | 拼接可读文案；不用于拼接未经校验的 SQL 值。 |
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |
| `bool` | 转换为明确布尔值。 |
| `all` | 要求所有证据或所有重复运行都满足条件，任何一项失败都不能算通过。 |
| `confirmation_facts` | 功能：提取确认结果的业务事实；get 读取动作、成功标记和工单，统一可选状态字段；不比较 reused 等重复请求提示元数据。 |
| `len` | 检查数量或长度限制。 |
| `turn['expect'].get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `assessed['checks'].values` | 遍历字典中的所有值。 |
| `classify_failures` | 功能：把失败断言映射成可分析的失败类型；FAILURE_RULES 提供严重级别，未细分断言归为业务目标未达到，不武断推断模型根因。 |
| `report['turns'].append` | 收集输出或测试统计。 |

### `summarize()`

[查看源码](../scripts/evaluate.py#L539)

功能：统计单次任务成功及用量；grouped_metrics 分类失败和重复运行稳定性，sorted/mean 计算 P95/均值，sum 保留通过数与总数。

| 调用 | 作用 |
|---|---|
| `any` | 判断是否存在非法字段。 |
| `result.get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `sum` | 累加通过数、Token 用量或失败次数，统计时保留分母。 |
| `turn['output'].get('usage', {}).get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `turn['output'].get` | 按键读取字典/请求头/Cookie；在路由装饰器中注册 GET，在测试客户端中发起 GET。 |
| `sorted` | 排序耗时样本。 |
| `grouped_metrics` | 功能：按类别/分组统计，并列出失败及多次运行稳定性；Counter 统计失败标签，set 汇总不同场景编号，保留分母而不抹掉异常用例。 |
| `len` | 检查数量或长度限制。 |
| `round` | 控制统计数值的小数位。 |
| `statistics.mean` | 计算已执行轮次的平均耗时；离线耗时不含远程模型推理。 |
| `max` | 取得最大值或约束计数下限。 |

### `main()`

[查看源码](../scripts/evaluate.py#L634)

功能：运行所选评测；validate_cases 先校验契约，Semaphore/gather 限并发与重复次数，run_case 执行业务，summarize 汇总并保存源码指纹。

| 调用 | 作用 |
|---|---|
| `argparse.ArgumentParser` | 建立管理或压测命令行入口。 |
| `parser.add_argument` | 定义命令行参数及默认值。 |
| `range` | 按确定次数准备账号或执行循环。 |
| `parser.parse_args` | 解析并校验命令行参数。 |
| `load_dotenv` | 从配置文件补充尚未设置的环境变量，不覆盖进程已指定的值。 |
| `json.loads` | 把 JSON 文本解码成字典或列表。 |
| `(storage.ROOT / 'data/eval_cases.json').read_text` | 读取 UTF-8 备份成功标记或测试文件。 |
| `validate_cases` | 功能：在付费调用前检查数据集契约；set 检查重复编号和未知断言，逐轮验证确认方式、角色与目标，避免拼错字段被静默忽略。 |
| `item.strip` | 删除首尾空白，识别空消息或空配置。 |
| `args.case.split` | 拆分命令行传入的逗号分隔场景编号。 |
| `parser.error` | 输出受控异常类别或 CLI 参数错误，不打印密码。 |
| `','.join` | 拼接可读文案；不用于拼接未经校验的 SQL 值。 |
| `sorted` | 排序耗时样本。 |
| `datetime.now(UTC).strftime` | 生成 UTC 时间文件名，便于辨认快照。 |
| `datetime.now` | 取得带时区的当前时间。 |
| `Path` | 构造本地路径。 |
| `output.parent.mkdir` | 创建目标目录。 |
| `datetime.now(UTC).isoformat` | 把到期时间转换为可保存的 ISO 时间文本。 |
| `Context` | 构造服务端运行上下文，包含真实用户、会话、请求和数据库位置。 |
| `len` | 检查数量或长度限制。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `path.relative_to` | 生成相对项目路径，作为报告中的源码指纹名称。 |
| `hashlib.sha256(path.read_bytes()).hexdigest` | 把摘要转换为十六进制字符串。 |
| `hashlib.sha256` | 计算不可逆 SHA256 指纹，用于 CSRF 派生、限流键或快照校验。 |
| `path.read_bytes` | 读取快照字节用于 SHA256 校验。 |
| `storage.ROOT.glob` | 列出参与评测的源码文件，逐个计算 SHA256。 |
| `Context().model.startswith` | 判断地址或模型名是否具有指定前缀。 |
| `os.getenv(key, '').strip` | 删除首尾空白，识别空消息或空配置。 |
| `os.getenv` | 读取环境配置，默认值用于本机启动。 |
| `output.write_text` | 保存人类可读的统计报告。 |
| `json.dumps` | 把报告编码为 JSON。 |
| `importlib.import_module` | 导入需要替换模型的模块。 |
| `asyncio.Semaphore` | 限制同时运行的场景数量，避免无限并发消耗模型资源。 |
| `max` | 取得最大值或约束计数下限。 |
| `min` | 取得最早租约到期或最小等待值。 |
| `tempfile.TemporaryDirectory` | 为压测创建独立临时目录，退出后自动清理。 |
| `asyncio.gather` | 等待各场景与重复运行完成，每次使用独立测试数据库。 |
| `evaluate` | 受信号量限制运行一个用例并增量写报告；并发用例使用不同 SQLite 文件。 |
| `summarize` | 功能：统计单次任务成功及用量；grouped_metrics 分类失败和重复运行稳定性，sorted/mean 计算 P95/均值，sum 保留通过数与总数。 |
| `all` | 要求所有证据或所有重复运行都满足条件，任何一项失败都不能算通过。 |
| `print` | 输出不含用户业务正文或凭据的管理/统计结果。 |

### `main.evaluate()`

[查看源码](../scripts/evaluate.py#L720)

受信号量限制运行一个用例并增量写报告；并发用例使用不同 SQLite 文件。

| 调用 | 作用 |
|---|---|
| `run_case` | 功能：驱动完整业务场景；seed_database 准备前置，run_request 执行/重放，confirm_action 模拟用户点击，check_turn 评分，SQLite 快照和审计保存证据。 |
| `str` | 将路径、编号或受控错误转换为文本。 |
| `Path` | 构造本地路径。 |
| `type` | 读取异常类型名称，避免输出异常中的私人文本。 |
| `report['cases'].append` | 收集输出或测试统计。 |
| `report['cases'].sort` | 按场景编号和重复次数排序，便于对照失败轨迹。 |
| `output.write_text` | 保存人类可读的统计报告。 |
| `json.dumps` | 把报告编码为 JSON。 |
| `print` | 输出不含用户业务正文或凭据的管理/统计结果。 |

## tests/test_evaluation.py

### `test_reject_fabricated_creation()`

[查看源码](../tests/test_evaluation.py#L18)

见定义上方中文说明。

| 调用 | 作用 |
|---|---|
| `answer_consistent` | 功能：按句核对明确状态及建单编号；split/finditer 提取可识别陈述，数据库和成功确认提供证据，其他句子的否定词不能掩盖错误。 |

### `test_reject_wrong_status_even_if_database_did_not_change()`

[查看源码](../tests/test_evaluation.py#L27)

见定义上方中文说明。

| 调用 | 作用 |
|---|---|
| `answer_consistent` | 功能：按句核对明确状态及建单编号；split/finditer 提取可识别陈述，数据库和成功确认提供证据，其他句子的否定词不能掩盖错误。 |

### `test_unconfirmed_write_fails_evaluation()`

[查看源码](../tests/test_evaluation.py#L39)

见定义上方中文说明。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_missing_required_tool_evidence_fails()`

[查看源码](../tests/test_evaluation.py#L62)

见定义上方中文说明。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_each_reply_is_compared_to_its_own_transaction_snapshot()`

[查看源码](../tests/test_evaluation.py#L72)

见定义上方中文说明。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_existing_correct_field_cannot_replace_execution_evidence()`

[查看源码](../tests/test_evaluation.py#L89)

功能：注入什么都没做的假成功；check_turn 必须因没有确认及审计失败，即使分派字段已经等于目标。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_unrelated_negation_cannot_hide_false_success()`

[查看源码](../tests/test_evaluation.py#L109)

功能：在错误状态前加另一句拒绝说明；answer_consistent 仍必须拒绝错误状态，同时允许真正的否定陈述。

| 调用 | 作用 |
|---|---|
| `answer_consistent` | 功能：按句核对明确状态及建单编号；split/finditer 提取可识别陈述，数据库和成功确认提供证据，其他句子的否定词不能掩盖错误。 |

### `test_creation_must_refer_to_the_ticket_actually_created()`

[查看源码](../tests/test_evaluation.py#L119)

功能：用一张真实建单结果为另一编号的假成功背书；answer_consistent 按编号对齐证据，防止仅检查任意确认成功。

| 调用 | 作用 |
|---|---|
| `answer_consistent` | 功能：按句核对明确状态及建单编号；split/finditer 提取可识别陈述，数据库和成功确认提供证据，其他句子的否定词不能掩盖错误。 |

### `test_plural_ticket_disclosure_is_detected()`

[查看源码](../tests/test_evaluation.py#L129)

功能：模拟查询列表泄露别人资料；check_turn 同时检查 ticket 和 tickets，不能只防单张详情。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_correct_faq_mixed_with_wrong_model_is_rejected()`

[查看源码](../tests/test_evaluation.py#L141)

功能：混入一条不适用型号的资料；check_turn 不能因正确 FAQ 也在结果里就放行全部资料。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_target_selection_and_unrelated_row_protection()`

[查看源码](../tests/test_evaluation.py#L157)

功能：构造两张工单并污染第二张；check_turn 按目标编号检查第一张状态，同时发现非目标写入。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_wrong_pending_parameters_and_memory_do_not_pass()`

[查看源码](../tests/test_evaluation.py#L180)

功能：还没有写库时也检查错误型号；check_turn 比较冻结卡片与结构化记忆，避免把零工单当成正确提案。

| 调用 | 作用 |
|---|---|
| `check_turn` | 功能：汇总逐轮断言；answer_consistent 核对回复时点，assess_contract 检查提案/审计/记忆，classify_failures 解释失败，不用 LLM 作唯一裁判。 |

### `test_dataset_contract_and_unknown_assertions()`

[查看源码](../tests/test_evaluation.py#L198)

功能：读取交付的全部用例，检查契约；deepcopy 故意拼错断言并复制编号，validate_cases 必须拒绝静默漏测。

| 调用 | 作用 |
|---|---|
| `json.loads` | 把 JSON 文本解码成字典或列表。 |
| `(storage.ROOT / 'data/eval_cases.json').read_text` | 读取 UTF-8 备份成功标记或测试文件。 |
| `validate_cases` | 功能：在付费调用前检查数据集契约；set 检查重复编号和未知断言，逐轮验证确认方式、角色与目标，避免拼错字段被静默忽略。 |
| `len` | 检查数量或长度限制。 |
| `next` | 从迭代器取下一项，或按编号找到目标工单/场景。 |
| `copy.deepcopy` | 复制完整测试对象，再注入错误字段；不污染原始样本。 |
| `pytest.raises` | 断言危险覆盖、冲突等操作会抛出预期异常。 |

### `test_repeated_run_summary_keeps_failures_in_denominator()`

[查看源码](../tests/test_evaluation.py#L216)

功能：同一任务两次运行一成一败，再加入运行器异常；grouped_metrics 必须保留全部运行，并把稳定通过与单次通过区分。

| 调用 | 作用 |
|---|---|
| `grouped_metrics` | 功能：按类别/分组统计，并列出失败及多次运行稳定性；Counter 统计失败标签，set 汇总不同场景编号，保留分母而不抹掉异常用例。 |

### `test_confirmation_metadata_may_change_but_business_facts_may_not()`

[查看源码](../tests/test_evaluation.py#L248)

功能：重复结果允许 reused 变化及补充当前状态，但不能换工单；confirmation_facts 规范业务字段，deepcopy 制造错误重放。

| 调用 | 作用 |
|---|---|
| `confirmation_facts` | 功能：提取确认结果的业务事实；get 读取动作、成功标记和工单，统一可选状态字段；不比较 reused 等重复请求提示元数据。 |
| `copy.deepcopy` | 复制完整测试对象，再注入错误字段；不污染原始样本。 |

## 记忆消融实验新增函数

这些函数仅服务隔离实验，线上业务模块未添加关闭记忆入口。先读固定场景，再沿 `main → run_case → assess_trajectory → summarize_ablation` 阅读。

### scripts/evaluate_memory.py

| 函数 | 功能及内部调用 |
|---|---|
| [`validate_ablation_cases()`](../scripts/evaluate_memory.py#L23) | 检查消融专用标记及评分边界。`validate_cases()` 继续验证原业务契约；字典推导创建副本，仅过滤已登记的消融标记，拼错字段仍会报错。 |
| [`assess_trajectory()`](../scripts/evaluate_memory.py#L51) | 逐轮核对实际回复。`startswith()`、`in` 对照 FAQ 原文与来源，识别真正展示的建议；`set.add()` 记录用户明确反馈失败的步骤；`any()` 判重，`all()` 要求本轮所有业务检查通过。 |
| [`summarize_ablation()`](../scripts/evaluate_memory.py#L101) | 按开/关组统计结果并建立逐场景配对。`sum()` 统计通过数、重复建议和用量；`statistics.mean()`、`sorted()`、`math.ceil()` 算平均值及 P95；只在配对齐全时计算通过率差，不把估算 Token 写入实际用量。 |
| [`save_report()`](../scripts/evaluate_memory.py#L191) | 保存中间和最终结果。`summarize_ablation()` 刷新指标；`json.dumps()` 编码，`write_text()` 写临时文件，`replace()` 原子替换，避免中断后 JSON 不完整。 |
| [`experiment_hashes()`](../scripts/evaluate_memory.py#L199) | 记录实验对应的代码和数据。`glob()` 找源码文件；`read_bytes()` 读取文件字节，`hashlib.sha256()` 计算指纹；`relative_to()` 保存相对项目路径。不会读取 .env。 |
| [`main()`](../scripts/evaluate_memory.py#L216) | 运行实验。`parse_args()` 读取模式和预算；`load_dotenv()` 加载已有模型配置；`validate_ablation_cases()` 先校验数据；`TemporaryDirectory()` 隔离数据库；`run_case()` 运行工具、确认和数据库流程；`assess_trajectory()` 评分，`save_report()` 逐次保存。离线用 `import_module()` 定位模型加载入口并临时替换，`finally` 恢复；真实模式有预算预检与连接错误中止。 |

### tests/test_memory_ablation.py

| 函数 | 功能及内部调用 |
|---|---|
| [`fixtures()`](../tests/test_memory_ablation.py#L19) | `read_text()` 和 `json.loads()` 读取冻结的场景和 FAQ，不在测试中修改源文件。 |
| [`test_ablation_has_fixed_inputs_and_no_internal_memory_oracle()`](../tests/test_memory_ablation.py#L27) | `fixtures()` 读样本，`validate_ablation_cases()` 检查契约；`len()`、`sum()` 核对 6 场景、22 轮；集合运算拒绝依赖内部记忆是否存在的评分。 |
| [`test_memory_off_preserves_history_and_repetition_is_observable()`](../tests/test_memory_ablation.py#L40) | `monkeypatch.setattr()` 注入固定模型；`asyncio.run(run_case())` 驱动两组真实工具链；`assess_trajectory()` 从可见建议判重。核对关闭组只清除记忆、聊天与摘要原样保留，最终仍可建单。 |
| [`test_repetition_scoring_requires_actual_user_failure_feedback()`](../tests/test_memory_ablation.py#L75) | `deepcopy()` 制作独立测试轨迹；`assess_trajectory()` 比较有无用户失败反馈，防止把普通重复展示也算成重复失败建议。 |
| [`test_missing_runs_and_estimated_tokens_are_not_success_or_actual_cost()`](../tests/test_memory_ablation.py#L102) | `summarize_ablation()` 汇总只完成一条的实验，断言计划分母仍为 18，缺失配对不产生提升数字，估算值不填入实际 Token。 |
| [`test_invalid_condition_rejected_before_database_is_created()`](../tests/test_memory_ablation.py#L128) | `pytest.raises()` 捕获 `run_case()` 对未知组别的拒绝；`Path.exists()` 确认还未创建数据库。 |
