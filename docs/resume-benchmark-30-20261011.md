# 30 份公开 Agent 相关履历：项目写法与技术深度对照

查阅日期：2026-10-11。目标：改写本项目在 **AI 应用／Agent 开发实习简历**中的介绍。

## 样本范围与使用方式

共 30 位不同作者：**20 份 PDF 简历、9 份个人履历网页、1 份 Markdown 履历**。网页样本包含个人站上的经历与项目介绍；不把它们称为 PDF 简历。均读到 Agent 相关经历或项目内容。只检索到标题、正文打不开的简历未计入；课程广告、通用简历模板、简历生成工具的说明书未计入。

这是按公开可访问性收集的便利样本，包含中国及海外作者，且海外样本较多，不能代表北京中小公司的实习招聘门槛、录用率或候选人排名。经历层次根据页面自述标注，不能通过项目介绍独立证明作者实际完成程度。本文所有外部成果数字均为作者自述，未核验原始实验或商业数据；只借鉴表达和设计，不采用这些数字作为我们的成果。

## 逐份对照

| # | 作者与原始履历 | 格式／经历参照 | Agent 相关内容与介绍特点 | 对我们的改写启发 |
|---|---|---|---|---|
| 01 | [林祥庆／Huoma LXQ](https://huomalxq.github.io/resume/) | 网页；硕士、Agent 实习 | 用 LangGraph 串联 Schema 检索、Text2SQL、校验重试和代码执行；分别报告表召回与端到端耗时。 | 区分中间能力指标和最终任务指标，写清定位瓶颈的办法。 |
| 02 | [HealthJian／Jian](https://healthjian.github.io/pages/about.html) | 网页；应届本科 | 电商 Agent 工作台包含业务域分工、人工审批、审计和执行可观测性；说明阶段交付情况。 | 写清哪些业务动作需要人确认；演示完成与部署计划分别表述。 |
| 03 | [Dai Yuxin](https://daiyuxin26.github.io/) | 网页；产品方向 | 长页项目集按背景、产品判断、状态流、权限和结果组织；涉及 LangGraph 企业协作及可恢复工作流。 | 先让读者理解业务问题；产品角色的收益不能冒充开发实习成果。 |
| 04 | [Elambharathi Thangavel](https://elambharathi.com/Portfolio/resume.pdf) | PDF；应用工程师 | Jira 编码 Agent 把检索、修改、测试重试、PR 与人工审批接起来，另写容器和云部署。 | 描述任务闭环；部署只有实际运行验收过才作为结果。 |
| 05 | [Ular Kimsanov](https://ularkimsanov.com/resume.pdf) | PDF；本科、软件实习 | 多 Agent 视频生成、LangGraph 预测市场与实时直播 Agent；同步延迟附有 2,221 个 cue 的测量规模。 | 延迟等数字要说明测量对象与样本量；实习经历和个人项目分别归属。 |
| 06 | [Ahmad Liaqat](https://ahmad786writes.github.io/assets/Resume/Ahmad_Liaqat_Resume.pdf) | PDF；工程师、技术负责人 | 语音点餐 Agent 使用固定工具白名单和真实菜单／购物车校验；28 轮脚本覆盖过敏、优惠、改单与语言切换。 | 把业务状态和工具校验写出来；失败案例解释设计为什么必要。 |
| 07 | [Aditya Mer](https://adityamer.live/resume.pdf) | PDF；本科、实习经历 | CrewAI 文献研究 Agent 描述自动检索和综合资料；该条目的测量证据较少。 | 仅有功能和框架仍难说明可靠性，我们补上业务验证与对照实验。 |
| 08 | [Ahmed Doghri](https://adoghri.com/assets/pdf/ADoghri%20Resume.pdf) | PDF；资深 AI 工程师 | Slack 知识助手、标签 Agent、RAG 评测和生产接口；同时写检索质量、延迟与业务规模。 | 数据应对应具体系统和评测口径；资深生产经验不作为实习必达标准。 |
| 09 | [Jacob J. Lee](https://jacobscript.dev/static/docs/Jacob_Lee_Resume_2024.pdf) | PDF；框架维护者，2024 版 | LangGraph.js／LangChain.js 维护与浏览器本地 RAG，强调开源贡献和传播范围。 | 框架贡献是另一类证据，不能通过使用同一框架推断项目等价；旧版数字不视为当前数据。 |
| 10 | [Akshay Jain](https://www.akshayjain.io/resume/Akshay-Jain_cyberSecurity-May2026.pdf) | PDF；安全负责人 | Agent 用于网络安全检测、威胁关联、权限审批和修复工单，围绕团队工作量报告收益。 | 权限与审计是业务约束；没有真实团队数据就不写节省人工比例。 |
| 11 | [Deepak Silaych](https://deepaksilaych.me/resume.pdf) | PDF；本科项目／比赛 | 语音 Agent、时间记忆及金融分析 Agent；金融项目给出数据集和相对普通 RAG 的结果。 | 组件效果要有基线；比赛或数据集结果不能等同线上效果。 |
| 12 | [Ben Wortman](https://ben-wortman.com/assets/resume.pdf) | PDF；GenAI 工程负责人 | MCP 接入沙盒、领域子 Agent、审计 Agent 和 DeepEval 回归；商业数字明确有预计节省的口径。 | 把真实收益、预计收益分开；回归评测可以成为项目主体的一部分。 |
| 13 | [Joy Krishan Das](https://joykrishan.github.io/assets/pdf/Joy_Krishan_Das_full_CV.pdf) | PDF；硕士研究 | 研究缺陷报告质量与修复 Agent 表现的关系，也列出软件修复和调度 Agent。 | 解释输入质量、失败原因和评分方法，比只写模型名称更有信息。 |
| 14 | [Mohammed Usmani](https://www.mohammedusmani.me/) | 网页；初级 AI 工程师 | 销售 Agent 分层装配上下文，Android Agent 由控制器判定完成；推荐改进附有 956 次观测的规模。 | 业务成功交给可信执行层；记忆工程要对应具体错误和结果。 |
| 15 | [Sattyam Jain](https://www.sattyamjjain.in/resume) | 网页；技术负责人 | 中央状态机、工具契约、人工审批、可撤销授权、沙盒和评测链路。 | 展开副作用和恢复边界；不能用一个“Agent”词概括全部工程。 |
| 16 | [Nebiyou Hailemariam](https://nebhailemariam.github.io/resume) | 网页；硕士、软件工程师 II | 汽车经销平台内的内容 Agent 与 MCP 服务，结合 LangGraph、FastAPI、LangSmith 和权限体系。 | 说明 Agent 如何嵌入后端业务；平台总用户量不能归为某个 Agent 的用户量。 |
| 17 | [Abhishek Choudhary](https://abh1shekchoudhary.github.io/) | 网页；本科、软件实习 | Phoenix 故障诊断按分类、决策、修改、验证、人工审批组织，并标注开发中；另有销售和邮件 Agent。 | 使用明确的阶段说明执行；开发中的能力不能写成已上线成果。 |
| 18 | [Dhanush C P](https://www.chandes.in/) | 网页；Agent 开发合同及研究实习 | Sakura 强调跨重启记忆、上下文预算、调用上限、工具重试与模型回退。 | 写记忆保存什么、何时恢复、如何限制执行；成本收益必须单独实测。 |
| 19 | [Alex Chandler](https://www.chandlerai.com/papers/alex-chandler-resume.pdf) | PDF；AI 工程及研究 | 语音服务 Agent 配套模拟用户、评分和回归平台，覆盖部署前行为验证。 | 端到端评测要模拟业务交互，检查完成状态而非只判断回答好不好。 |
| 20 | [Anthony Rodez](https://rodeza.github.io/resume/Rodez-Resume.pdf)；[履历仓库的项目补充](https://github.com/RodezA/resume) | PDF；资深 AI／数据工程师 | PDF 概括 AI 工程经历；履历仓库补充多 Agent 预测、金融 RAG 与独立评测 Harness 项目。 | 履历概述和项目详情可以分层；说明评测与实现的边界。 |
| 21 | [Daniel Rosehill](https://github.com/danielrosehill/AI-Resume/blob/main/resume.md) | Markdown；自动化与技术沟通 | 本人的 Markdown 履历列 Agent 编排、自动化实施和技术文档经历；不是把仓库中的简历格式说明算作另一份简历。 | 文档与知识管理有工程价值；笼统经验描述不能当作已量化项目证据。 |
| 22 | [Lakshit Gupta](https://www.lakshit.dev/public/Lakshit_s_CV_Portfolio.pdf) | PDF；本科、AI／软件实习 | LangGraph Reflexion 项目描述条件路由、自评与答案改进，另列 RLHF 评测实习。 | 自反思循环是一种实现选择，项目仍应提供该机制的效果证据。 |
| 23 | [Sam Latino](https://samlatino.dev/resume/) | 网页；开源项目、跨领域经历 | 确定性 Agent 安全探针、工具调用契约测试、BM25 基准和带重复噪声控制的评测 CI。 | 小项目也可用明确失败类型、重复实验和可复现报告体现深度。 |
| 24 | [Abdul Basit](https://abdulbasit-dev.netlify.app/abdul-basit-resume.pdf) | PDF；资深全栈工程师 | CRM Agent 使用检查点、分析缓存、SSE、写入审批和 Token 配额；确定性业务评分与模型分工明确。 | 检查点、业务数据和缓存分别说明；成功判定与写操作要有可信依据。 |
| 25 | [Darren Tang](https://tangdarren.com/resume/Darren_Tang_Resume.pdf) | PDF；硕士、Agent 实习 | CRM 工作队列 Agent、企业数据工具与报销 Agent，围绕审核时间和评测任务描述结果。 | 实习项目可以直接围绕一段业务流程；收益数字需要自己的观测证据。 |
| 26 | [Chad Bartley](https://chadbartley.github.io/chadbartley-site/Chad-Bartley-Resume.pdf) | PDF；资深工程师、创业 | Agent Runtime 和 AI BI 连接商业客户及生产交付；另列基础设施成本优化。 | 运行规模与技术贡献分别归属；个人演示项目不借用商业交付用语。 |
| 27 | [Ryan Huang](https://ryanxhuang.com/resume.pdf)；[MCP 项目补充](https://ryanxhuang.com/) | PDF；机器人产品方向 | 简历含 MCP 三维建模与客户服务 AI；个人履历页补充自然语言驱动 Rhino API 的流程。 | 工具连接具体专业任务；机器人和产品方向仅作邻近参照。 |
| 28 | [M Rupesh Kumar Yadav](https://rupesh-dev.vercel.app/resume.pdf) | PDF；硕士、研究实习 | 多 Agent 知识助手用分流、HR／技术域 Agent、层级 RAG、重排与 Guardrail 组织查询。 | 解释每个组件解决的问题；一般 ML 项目的准确率不能转用于 Agent 条目。 |
| 29 | [Sanjit Shrestha](https://sanjitshrestha.github.io/Sanjit%20Shrestha%20CV%202026.pdf) | PDF；资深后端／技术负责人 | PortalFlow 用 Django、LangGraph 和 Playwright 做有状态浏览器自动化，和其它后端产品分别列项。 | 系统状态和失败恢复有简历价值；其它服务吞吐不代表 Agent 吞吐。 |
| 30 | [Shahzaib Khan](https://shahzaib.ai/cv) | PDF；AI 应用工程师、团队负责人 | 酒店／会议 Agent、MCP 集成、语音 Agent 与法律文档工具；研究条目写出模型和人工基线的差距。 | 可以如实报告相对基线结果和未达人工的部分；业务、工程与研究指标分别解释。 |

## 对照后对我们项目的判断

这里比较的是**履历中展示的证据深度**，不是候选人能力排名。学生样本提供直接的实习表达参照；资深样本只用于学习工程设计和证据组织。

1. **功能闭环**：我们的 FAQ → 多轮排查 → 待确认操作 → 工单状态流转能解释清楚 Agent 的任务。简历用一句交代这条业务线，不展开 40 项功能清单。
2. **业务记忆**：保存型号、故障、已尝试步骤和当前工单，并有固定场景对照。比“支持多轮对话／长期记忆”更容易验证和追问。
3. **可靠写操作**：人工确认、参数绑定、权限和版本复核、事务、幂等与审计，直接对应误建单、越权、重复执行和虚假成功四类问题。
4. **评测证据**：用真实业务状态评分，有场景数、轮数和重复次数。保留离线执行验证与真实模型实验的区别。

因此，推荐定位是“**具备业务记忆、可靠工具执行和可复现评测的售后 Agent 个人项目**”。能支持实习简历的工程讨论；目前没有真实客户流量、公网交付验收和独立盲测，不写成企业生产平台。本样本也不足以证明在北京候选人中的竞争排名。

## 改写采用与不采用的内容

| 旧式表达 | 本次改写 |
|---|---|
| 使用 LangChain、LangGraph 开发智能客服 | 说明模型选择工具，后端控制业务写入和成功确认 |
| 支持聊天记忆，提升多轮效果 | 写保存的业务事实，以及 6 场景 × 每组 3 次的真实模型对照结果 |
| 加入确认、权限和异常处理 | 写提议 → 用户确认 → 事务执行的边界与重复确认实验 |
| 完成 40 项增强，测试全部通过 | 写 60 场景、74 轮离线业务验证，以及具体检查的数据库状态和审计 |
| 企业级、高并发、线上成功率 100% | 无对应证据，不采用 |

最终可复制条目与数字依据见 [resume-project.md](resume-project.md)。没有为了对齐外部履历增加 MCP、多 Agent、向量数据库或模型微调，也没有修改业务代码。
