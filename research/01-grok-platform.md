# Grok Bot 个人投资平台：官方能力核验与初始架构建议

> 调研日期：2026-09-20（Asia/Shanghai）  
> 范围：真实的 **Grok Bot** 产品（https://x.ai/bot），并与 Grok Chat、xAI API、Grok Build、Cursor Agent/Cloud Agent 区分。  
> 证据口径：只把 xAI/SpaceXAI 与 Cursor 官方页面中明确写出的能力记为“已确认”；Marketplace 模板只证明“官方市场当前展示了这种实现方式”，不等于平台 SLA；未在官方材料中找到的能力标为未知，不以 API 能力反推 Bot 产品能力。

## 1. 结论先行

Grok Bot 适合作为个人投资平台的“常驻研究与协调层”，而不是行情数据库、券商交易系统或确定性调度引擎。它的强项是：每个用户拥有一台持续在线的云电脑；多个具名 Bot 保留各自角色记忆并可并行工作；所有 Bot 共用文件、浏览器登录和命令行凭据；Routine 可按时间或部分应用事件启动；手机端可发起任务、查看结果、审批、接管登录步骤；Bot 之间可异步消息、群聊和移交工作。

推荐首版只设 **1 个 Chief of Staff + 4 个专职 Bot**，全部默认只读、只产出草稿，不下单：

1. **Investment Chief of Staff（总控）**：收集各专员回执，合并冲突，产出晨报/周报和“需本人决策”清单；不直接做深度抓取，也不拥有券商写权限。
2. **Market & Catalyst Scout（市场与催化剂）**：定时读取 X、公开新闻、公告和日历，输出带时间戳的事件变化；只报告新增或显著变化。
3. **Company Research Analyst（公司研究）**：对单一标的维护证据包、来源、假设、反证和待核实项；重大结论必须回查当前来源，不能依赖 Bot 记忆。
4. **Portfolio & Risk Monitor（组合与风险）**：读取只读持仓/成交回单/观察列表，做敞口、集中度、事件风险和数据新鲜度检查；任何订单建议均停在草稿/审批前。
5. **Data & Evidence Steward（数据与证据）**：维护 `/workspace/investing/` 中的规范化文件、来源清单、去重键、运行回执和失败记录；负责连接器/MCP/CLI 的健康检查，不负责投资判断。

这套结构利用了 Grok Bot 的真实产品原语：Bot、聊天、Skill、Routine、工具、Artifact，以及 Bot 间异步消息/群聊。它也顺应官方建议“先跑一次真实任务，稳定后保存为 Skill，第二个输入上测试，再创建 Routine”，避免一开始把未经验证的流程长期自动化。

## 2. 产品边界：四个容易混淆的表面

| 产品面 | 官方定位 | 是否等同于 Grok Bot | 对本项目的正确用法 |
|---|---|---:|---|
| **Grok Bot** | 持久 Bot、共享云电脑、浏览器/文件/终端、Routine、审批、多 Bot 协作、移动端 | 是 | 研究协调层与常驻工作台 |
| **Grok Chat / grok.com** | 对话、搜索、文件分析、连接器、图像/视频/语音；另有 Grok Automations | 否 | 可作为单次研究工具；不要把 Chat Automations 的全部触发器/计费直接套到 Bot Routine |
| **xAI API** | 模型调用、Web/X Search 等开发接口，按 API 文档和 API 计费 | 否 | 自建服务可调用；API 有某工具不代表 Grok Bot UI 有同一功能或同一限制 |
| **Grok Build CLI** | 终端编码代理，支持模型选择、插件、MCP、hooks、subagents、CLI 命令 | 否 | 可在 Bot 云电脑终端中作为一种工具使用，但不是 Grok Bot 的管理 CLI |
| **Cursor Agent / Cloud Agent** | 面向代码仓库的本地/云端编码代理；Cloud Agent 通常按任务创建隔离 VM、改代码、测试、开 PR | 否 | 让 Grok Bot 做“外环”研究/协调，必要时将明确的代码任务交给 Cursor Cloud Agent |

官方实例明确演示了这种分层：Grok Bot 先从 Slack、Notion、GitHub、文档收集上下文，再把干净提示交给 Cursor Cloud Agent；作者特别说明 Grok Bot 本身并不是在该流程中写代码，而是在调度专门的 Cursor 编码 harness。参见 [Grok Bot 101](https://x.ai/bot/guides/grok-bot-101) 与 [Cursor Cloud Agents](https://cursor.com/docs/cloud-agent)。

## 3. 平台能力核验表

状态说明：**已确认**＝官方文档/产品页明确；**部分确认**＝能力存在但范围、推出状态或保证不足；**未确认**＝未找到官方产品证据。

| 能力 | 状态 | 官方证据/限制 | 对投资平台的含义 |
|---|---|---|---|
| 24/7 后台工作 | 已确认 | Bot 工作与 Routine 在 Cursor 云电脑运行，关闭笔记本/手机不停止；官方称 always-on、24/7。 | 可做跨时区监控，但仍受用量、登录过期、网站阻拦、Routine 暂停影响，不能把宣传语当成 SLA。 |
| 多 Bot 并行 | 已确认 | 多 Bot 可同时推理、用连接器和文件；每个 Bot 在共享电脑上有独立屏幕；同一 Bot 的同一屏幕一次只能跑一个 computer-use 任务。设计文称约 50 Bot/账户、群聊最多 6 Bot。 | 用少量专职 Bot 分工；不要给单 Bot 同时塞多个浏览器操作。首版 5 Bot 正好可在一个群聊协调。 |
| 共享电脑/文件 | 已确认 | 一个用户的所有 Bot 共用一台持久云电脑、`/workspace`、浏览器 cookies/session、命令行凭据；屏幕不是安全边界。 | 建统一目录与交接清单很合适；**不同 Bot 不能当权限隔离**。敏感券商写权限不得仅靠“交易 Bot 与研究 Bot 分开”隔离。 |
| 浏览器与登录 | 已确认 | 可浏览网站、操作无 API/MCP 的服务；登录会话可持续。密码、2FA、CAPTCHA、支付/身份检查应交给人接管；网站可阻断自动化或使 session 过期。 | 新闻、IR、券商门户可用浏览器补位；关键数据优先连接器/API，Routine 需定义登录失效分支。 |
| 本地电脑访问 | 已确认 | 云电脑与本机分开；本机命令执行默认 Ask every time，可 Always allow/Never allow，团队策略可收紧。 | 首版设 Never allow；若确需读取本机研究库，再按设备、按命令开放。 |
| 定时 Routine | 已确认 | 可按时区设一次、日/工作日/周/月/年及文档示例中的每 30 分钟；后台运行。每 Bot 最多 50 个 Routine，保留每 Routine 最近 20 次运行记录。 | 足够覆盖晨报、盘前、收盘、周末复盘；审计留存只有 20 次，需把长期回执写入 `/workspace` 或外部库。 |
| 事件触发 | 部分确认 | 官方示例含 Slack、GitHub、Linear、webhook 等事件；具体触发器取决于 Cursor 账户集成，且与普通插件连接是两套流程。 | 不假设任意金融数据源都能直接触发。行情阈值/成交回单事件应由自建 MCP/webhook 或外部调度器验证后接入。 |
| Bot 间移交 | 已确认 | Bot 可异步发消息唤醒对方、稍后回复；群聊可共享项目上下文并传递所有权；Bot-to-group handoff 当前仅文本，需看图时应直接发给目标 Bot。 | 用结构化文本回执 + `/workspace` Artifact 交接；总控只合并，不重新抓全量数据。 |
| 记忆 | 已确认但非权威源 | Bot 保留稳定偏好、角色上下文和历史工作摘要；每个 Bot 的会话/学习上下文分开，文件、浏览器、群聊、直接移交可跨 Bot。官方要求重大决策回查当前来源。 | 记忆保存格式偏好、投资框架、审批边界；价格、持仓、财报值、评级等易变事实只放权威数据源和带时间戳 Artifact。 |
| Skill / 示范学习 | 已确认/渐进推出 | Skill 是跨 Bot 共享的可复用指令；Teach a task 可录制最长 10 分钟的可见浏览器操作并生成草稿 Skill，功能可能分批开放，且仍需补决策规则、失败处理、审批边界。 | 可录制下载券商报告、导出 watchlist 等操作；不能把一次成功录制当作稳健自动化。 |
| 连接器/Marketplace | 已确认 | 连接器以 Marketplace plugin 安装、账户级共享，可用 `@` 附加；官方建议有连接器时优先于网页点击。Marketplace 还提供 Bot 模板、Skills、Routines 和 integrations 的组合。 | 优先结构化读接口；安装模板前检查上下文、集成和权限，不直接信任社区模板。 |
| MCP | 部分确认 | 官方指南称 Grok Bot 支持与 Cursor 相同的 MCP servers/plugins/skills；团队/企业文档提到 Enterprise MCP allowlist。Bot 文档未给出一份完整的个人账户 MCP 安装/传输/生命周期规范。 | 可以规划自建只读金融 MCP，但要在实际账户中验证安装方式、网络可达性、认证和 Routine 调用；不要把 grok.com Connector 或 Grok Build CLI 的 MCP 配置步骤原样当 Bot 配置。 |
| CLI/终端 | 已确认但边界明确 | Bot 云电脑有终端、可写/运行代码；Marketplace 的 Researchy 模板公开展示在云电脑运行官方 `grok` CLI。Grok Build CLI 自己支持 `grok models`、`grok mcp`、plugin 等命令。 | 可在数据管线中使用 CLI；未找到“用 CLI 创建/管理 Grok Bot、Routine、群聊”的公开产品能力。 |
| 模型选择 | 已确认无选择器 | Grok Bot 设置文档明确：模型由 Cursor 管理，产品中没有 model picker。Marketplace 模板可通过云电脑里的 Grok CLI 显式选 `grok-4.6`，那是子进程工具，不是 Bot 自身模型设置。 | 架构不能依赖“每个 Bot 固定指定模型”；需要特定模型的核验步骤可作为 CLI 子任务，但增加成本与故障面。 |
| 用量/限制 | 已确认到机制，额度未公开固定 | 订阅含每周 Grok Bot 用量；符合条件账户可按模型/Token 成本增加 on-demand usage；用尽或触及消费上限时任务可卡住/暂停。若同时有 Cursor 与 SuperGrok，FAQ 称使用额度更多的一方。 | Routine 必须有“用量不足”异常和每日健康检查；预算应从实际账户 Usage & Billing 读取，不能用 API 价格推算 Bot 固定吞吐。 |
| 移动端 | 已确认 | iOS 18+/iPadOS 18+、Android 9+；同一 Bots、会话、Routine、连接器和共享电脑；可启动任务、审批、查看/接管电脑、暂停/恢复/删除 Routine。编辑 Routine 计划/指令和 Test run 当前需桌面端；推送仍在逐步推出。 | 手机适合作为审批台与故障接管台；不能把移动 push 当唯一告警渠道，关键失败另写外部告警。 |
| 权限/审批 | 已确认 | 明确请求边界 + model-based Auto Review；Ask first 优先于 Allow automatically。密码/2FA/CAPTCHA 由人接管。批准只控制将要执行的动作，不会撤销已经完成的动作。 | 所有发送、发布、删除、购买、转账、改权限、生产变更设 Ask first。投资平台首版不要接订单写权限。 |
| 部署位置 | 已确认 | 每用户一台 Cursor 云中的持久 Firecracker microVM；桌面/移动 App 是聊天、查看、审批的薄客户端。企业可做网络、审计、Team Setup 等额外控制。 | 无需自托管 Bot 运行时；自建行情/MCP 服务仍需单独部署。个人版能力不能假设包含企业 Network Controls/Action Recording。 |
| 失败行为/恢复 | 已确认 | UI 有 idle/working/waiting/blocked/thinking/done；可检查审批/登录/CAPTCHA。Routine 有成功失败历史；数据源、插件、网络、用量、账户均可致失败。长时间离开后系统可能询问是否继续，未响应可暂停 Routine。Recover/Update 尽量保留文件和登录，Reset 回最近快照且可能丢近期未同步工作。 | 每个 Routine 写明 stale/no-data、幂等重试、部分完成、失败回执；Artifact 及时存 `/workspace` 和外部备份。不要默默沿用旧行情。 |
| 交易/资金动作 | 平台可操作，但不应默认开放 | 浏览器理论上可像人一样操作已登录账户；官方审批指南把购买、金融转账列为必须明确边界的高后果动作。没有面向个人投资的官方交易 SLA、风控或订单幂等保证。 | 将 Grok Bot 限制为只读研究、核对和订单草稿；真正下单由用户在券商端完成，或由独立、确定性且审计完备的交易系统承担。 |
| 公共 Grok Bot 管理 API | 未确认 | 检索到的 xAI API 与 Cursor Cloud Agents API 均是别的产品面；官方 Bot 文档未明确公开 Bot/Routine 生命周期 API。 | 初版通过产品 UI/聊天配置；不要把“可调用 xAI 模型 API”写成“可编程创建 Bot”。 |

主要官方依据：[Grok Bot Overview](https://docs.x.ai/grok-bot/overview)、[Get started](https://docs.x.ai/grok-bot/get-started)、[Computer and apps](https://docs.x.ai/grok-bot/computer-and-apps)、[Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)、[Chat and collaboration](https://docs.x.ai/grok-bot/chat-and-collaboration)、[Approvals/security/privacy](https://docs.x.ai/grok-bot/approvals-security-and-privacy)、[Mobile](https://docs.x.ai/grok-bot/mobile)、[Settings](https://docs.x.ai/grok-bot/settings-and-notifications)、[Troubleshooting](https://docs.x.ai/grok-bot/troubleshooting)、[FAQ](https://docs.x.ai/grok-bot/faq)。

## 4. 初始投资研究工作流

### 4.1 共享目录与交接契约

建议在共享电脑中建立：

```text
/workspace/investing/
  config/             # 标的、时区、数据源、阈值；不放 secret
  inbox/              # 本轮待处理输入
  sources/            # URL/文件清单及抓取时间
  entities/           # 按 ticker/issuer 的长期证据包
  portfolio/          # 只读持仓快照与来源时间
  runs/YYYY-MM-DD/    # 每次 Routine 回执
  reports/            # 晨报、事件报告、周报
  decisions/          # 用户决定和理由；不等于自动交易授权
  failures/           # 登录、数据过期、连接器、用量等失败记录
```

每个 Bot 的交接回执至少包含：`run_id`、开始/结束时间与时区、输入来源及数据时点、完成项、未完成项、事实、推断、冲突、未知、产物路径、建议、是否需要用户决策。这样既利用共享文件，又不把文件存在当成“已通知”。最终结果仍需在对话中给出摘要和明确链接。

### 4.2 建议 Routine

| Routine | 所有者 | 触发 | 输出 | 失败策略 |
|---|---|---|---|---|
| Source health check | Data Steward | 每日 06:30 | 登录/连接器/数据新鲜度/用量检查 | 任一关键源异常即阻止下游使用旧数据，并通知总控 |
| Morning market brief | Market Scout | 工作日 07:30 | 隔夜事件、当天日历、观察列表催化剂，全部带来源时间 | 无新增则静默；关键源缺失则明确“不完整” |
| Portfolio risk snapshot | Risk Monitor | 工作日盘前及收盘后 | 只读持仓、集中度、事件风险、待核对异常 | 持仓时点不新鲜则不输出结论，只报失败 |
| Watchlist deep-dive queue | Company Analyst | 每日一次或按人工指派 | 最高优先标的证据包更新 | 来源冲突并列展示，不自动裁决 |
| Chief daily synthesis | Chief of Staff | 上游完成后或固定 08:15 | 5 条以内重点、变化原因、证据、需决策项 | 等待超时后交付“部分完成”并列出缺口 |
| Weekly thesis review | Chief + Analyst + Risk | 周末 | 论点变化、反证、组合影响、下周验证清单 | 不生成买卖指令；需要人工确认后才更新正式 thesis |

官方支持 Bot 异步唤醒另一个 Bot，但对于“所有上游都完成后再合并”的严格 fan-in 语义，文档没有给出确定性工作流引擎保证。因此首版最好让总控按固定截止时间读取每个 `run_id` 回执；缺失就标“未完成”，不要无限等待或假装齐套。

### 4.3 数据与执行边界

- **事实源**：行情、持仓、成交、财报、公告必须带 `as_of`、来源和查询结果；Bot memory 只存规则与偏好。
- **金融连接**：官方 Marketplace/文档未证明内置 Finnhub、Tiingo、FMP、AKShare、IBKR Flex、Longbridge 等个人投资连接器。若现有 `sec-analysis` CLI 确有这些只读接口，应将其视为待现场验证的外部工具，不算 Grok Bot 原生能力。
- **X 数据**：官方已确认 Grok Bot 可连接 X，搜索帖子、读取 timeline/mentions/trends/bookmarks；适合事件发现，不应单独作为投资事实来源。参见 [Grok Bot now works with X](https://x.ai/news/grok-bot-and-x)。
- **写操作**：首版不配置券商交易凭据，不自动发帖/发邮件，不更改 watchlist 之外的外部状态。即使 Auto Review 可阻断，也不能把基于模型的 reviewer 当成金融风控系统。
- **模板**：Marketplace Bot 是实现参考而非审计过的投资产品。模板复制的是指令、相关记忆、Skills、部分 plugins/routines 的“配方”；不会带走原电脑、登录和会话，非标准 MCP/脚本也可能需另行搬运。参见 [Templates for Grok Bot](https://x.ai/bot/guides/templates-for-grok-bot)。

## 5. 官方实例中最值得借鉴的模式

1. **Chief of Staff 用例**：官方建议扫描已批准的 Slack、邮件、日历、会议笔记，只返回与优先级相关的变化；每条包含来源、为何重要、建议下一步、是否欠一个决定，而且不自行发送或改日历。该结构可以原样迁移成投资晨报。见 [Grok Bot use cases docs](https://docs.x.ai/grok-bot/use-cases)。
2. **Grok Bot 101 的“外环/内环”**：总控 Bot 清理跨系统上下文，再交给专门执行器；避免让同一代理一边漫游式收集、一边立刻执行高后果操作。投资场景中对应“研究协调 Bot → 确定性数据工具/分析脚本”，而不是“研究 Bot → 自动下单”。
3. **Haggle Bot（官方团队发布文章）**：同时读费用、合同、使用量和市场报价，维护逐供应商档案；内部研究/协调可自主完成，花钱、接受条款、联系供应商必须显式批准。对应投资场景是逐发行人 dossier，以及“研究可自动、资金动作必须人工”。见 [Setting Grok Bot loose on procurement](https://x.ai/news/grok-bot-procurement)。
4. **Researchy Marketplace 模板**：公开写明每次研究用最新 Grok + live search、结果需 sourced/dated，并通过云电脑内 Grok CLI 执行。这证明“Bot 调 CLI 做专门研究”是可实现模式；它不证明该 CLI 是 Bot 管理面，也不保证模板作者的模型/费用设置适用于你的账户。见 [Researchy](https://x.ai/bot/marketplace/bots/researchy)。
5. **GTM Account Research 模板**：要求来源范围、新鲜度、去重、冲突规则、read/draft/write 权限、空结果行为、Routine 默认关闭，并以结构化 artifact 在专员之间交接。虽然是销售研究，这套治理几乎可直接迁移到证券研究。见 [GTM Account Research](https://x.ai/bot/marketplace/bots/account-research)。
6. **Deal Hunting 模板**：公开展示工作日 09:30 的 watchlist Routine 和周五 16:30 的过程改进 Routine，并要求显式地点/币种、禁止自行购买。它证明 Marketplace 模板页面能展示 memories/routines，但仍是第三方模板，不是平台保证。见 [Deal Hunting](https://x.ai/bot/marketplace/bots/deal-hunting)。
7. **官方 Marketplace 的 Morning Newspaper / Competitor Watch / last30days**：分别体现“多源定制简报”“只报真实变化”“跨 Reddit/X/YouTube/TikTok/HN/Polymarket/GitHub 的近期研究”。适合借鉴数据源编排和降噪方式，不应直接采信其结论。见 [Grok Bot Marketplace](https://x.ai/bot/marketplace)。

## 6. 权限与安全设计

建议个人账户的起始规则：

- `Execution on Local Computer = Never allow`，直到确有本机文件需求。
- 对发送外部消息、发布、删除/覆盖、购买、转账、接单/下单、改变权限、安装未知软件、写入生产系统统一设 **Ask first**。
- 研究数据连接优先使用只读 OAuth scope、只读 API key 或只读券商报表账户；不要把主交易账户的可写凭据放在共享电脑。
- 所有 Bot 共用云电脑与登录，所以“专员分工”只改善上下文，不提供秘密隔离。若两个工作域不能互相看到凭据，应使用不同用户账户/不同外部服务凭据边界，而不是不同 Bot。
- 密码、2FA、CAPTCHA、支付确认只在接管/安全表单完成，不贴到普通聊天。
- Auto Review 是 model-based；官方也明确要求它只补充最小权限与明确审批边界。允许规则应细到已知命令与目录，例如只允许 `/workspace/investing` 下的只读状态/生成报告命令。
- 删除 Bot 不会清掉共享电脑文件和浏览器 session；撤权时要依次暂停 Routine、网站登出、卸载/撤销连接器、清理 `/workspace` 敏感文件，再处理 Bot。

## 7. 失败、恢复与可观测性

Grok Bot 产品已提供运行状态、Routine 最近成功/失败历史、通知、电脑预览/接管、Retry/Recover/Update/Reset。仍需自行补足投资平台级别的可观测性：

- 每个 Routine 落一份长期 run receipt；平台内仅保留最近 20 次 Routine 记录，不够季度审计。
- 任一输入必须标时间；超过阈值即 stale，不能静默沿用。
- 重试必须幂等，例如同一 `run_id + source_version` 不重复写正式报告或外部系统。
- 总控报告可“部分完成”，必须列缺失专员、失败原因和影响范围。
- 关键失败不要只依赖移动 push，因为官方说 push 仍在逐步推出；至少保留 in-app attention，并考虑一个经验证的外部通知通道。
- Routine Test run 会执行真实动作；只能在安全输入和只读连接上测试。
- Reset 可能丢失最近未同步工作，因此正式 Artifact 应及时写入 `/workspace`，重要证据还应同步至外部受控存储。

## 8. 尚未证实、必须在 PoC 中验证的问题

1. 当前个人账户实际可用的 Bot 数、并发、每周用量、on-demand 单价、Routine 运行成本和限流；官网没有给出适合容量规划的固定 token/任务额度。
2. 账户中是否已经出现 Teach a task、事件触发器、自定义 MCP 安装入口、所需金融连接器，以及这些功能在个人/Teams/Enterprise 的差异。
3. Routine 的重试次数、超时、错过计划后的补跑语义、上游 Bot 完成事件能否可靠触发下游、并发冲突时的排队规则；官方只提供操作与故障排查，没有完整调度语义/SLA。
4. Bot memory 的容量、摘要策略、可导出/可编辑性和保留期限；官方只说明记忆类型和边界。
5. 云电脑备份/快照频率、`/workspace` 的容量与长期保留、Reset 能回到多新的 snapshot；文档只说明恢复行为，未给量化保证。
6. Grok Bot 是否有公开、稳定的 Bot/Routine 管理 API；当前不应假设有。
7. MCP 在 Grok Bot 个人账户中的正式配置方式、支持的 transport、认证刷新、后台 Routine 中的可用性；不能用 Grok Chat connector 或 Grok Build CLI 文档替代实测。
8. X API 免费 credits 的额度、刷新周期、速率限制和可用 endpoint；官方公告只说付费 Bot 用户获得起始免费 credits。
9. 各金融网站对自动化的条款、反爬、CAPTCHA、登录期限；“浏览器能点”不等于合规、稳定、可长期无人值守。
10. 现有 `sec-analysis` Python CLI 关于 Finnhub、Tiingo、FMP、AKShare、IBKR Flex T+1、Longbridge 只读/watchlist 的声明目前只来自项目交接信息，本次没有现场连接或凭据验证，不能作为当前可用能力承诺。

## 9. 推荐 PoC 验收门槛

用两周只读 PoC 决定是否扩展：

1. 只创建 Chief、Market Scout、Data Steward 三个 Bot；先不用五个全量角色。
2. 人工跑通一次“隔夜变化 → 来源核验 → 晨报”，再保存 Skill；用第二天数据复测。
3. 建一个工作日 Routine，明确时区、输入、空结果、stale、审批和失败回执；连续 5 个交易日观察。
4. 验证手机端能看到结果、审批和接管；桌面端能编辑/Test Routine。
5. 故意制造四种失败：数据源无数据、登录过期、CLI 非零退出、用量/权限不足；必须无旧数据伪装成功。
6. 检查 Bot A 保存的文件能由 Bot B 读取，同时确认二者也会共享登录，证明这不是权限边界。
7. 验证每条报告结论能回到 URL/文件、时间戳和原始字段；事实、推断、建议分栏。
8. 全程不授予交易权限。只有当研究链稳定、失败可见、审计可回放后，再单独评估“订单草稿”，仍不建议自动提交。

## 10. 官方来源索引（便于复核）

### Grok Bot 产品与文档

1. [Grok Bot 产品主页](https://x.ai/bot)
2. [Introducing Grok Bot](https://x.ai/news/introducing-grok-bot)
3. [Designing Grok Bot for a world of persistent agents](https://x.ai/news/designing-grok-bot)
4. [Grok Bot 官方文档总览](https://docs.x.ai/grok-bot/overview)
5. [Get started](https://docs.x.ai/grok-bot/get-started)
6. [Create and manage Bots](https://docs.x.ai/grok-bot/bots)
7. [Message and collaborate](https://docs.x.ai/grok-bot/chat-and-collaboration)
8. [Files and results](https://docs.x.ai/grok-bot/files-and-results)
9. [Use the computer and apps](https://docs.x.ai/grok-bot/computer-and-apps)
10. [Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)
11. [Approvals, security, and privacy](https://docs.x.ai/grok-bot/approvals-security-and-privacy)
12. [Settings and notifications](https://docs.x.ai/grok-bot/settings-and-notifications)
13. [Grok Bot for Mobile](https://docs.x.ai/grok-bot/mobile)
14. [Troubleshooting](https://docs.x.ai/grok-bot/troubleshooting)
15. [Grok Bot FAQ](https://docs.x.ai/grok-bot/faq)
16. [Grok Bot for teams and enterprises](https://docs.x.ai/grok-bot/teams-and-enterprises)
17. [Use cases 文档](https://docs.x.ai/grok-bot/use-cases)
18. [Grok Bot Use Cases 页面](https://x.ai/bot/use-cases)
19. [Grok Bot Guides](https://x.ai/bot/guides)
20. [Grok Bot 101](https://x.ai/bot/guides/grok-bot-101)
21. [Templates for Grok Bot](https://x.ai/bot/guides/templates-for-grok-bot)
22. [Grok Bot Marketplace](https://x.ai/bot/marketplace)
23. [Grok Bot now works with X](https://x.ai/news/grok-bot-and-x)
24. [Setting Grok Bot loose on procurement](https://x.ai/news/grok-bot-procurement)

### 用于产品边界对照

25. [Grok Chat 产品总览](https://docs.x.ai/grok/overview)
26. [Grok Automations](https://x.ai/news/grok-automations)
27. [xAI API Models & Pricing](https://docs.x.ai/developers/models)
28. [Grok Build CLI Reference](https://docs.x.ai/build/cli/reference)
29. [Grok Build Skills, Plugins & Marketplaces](https://docs.x.ai/build/features/skills-plugins-marketplaces)
30. [Cursor Agent Overview](https://cursor.com/docs/agent/overview)
31. [Cursor Cloud Agents](https://cursor.com/docs/cloud-agent)
32. [Cursor Cloud Agent Automations](https://cursor.com/docs/cloud-agent/automations)

### Marketplace 实现参考（第三方/模板，不是平台保证）

33. [Researchy](https://x.ai/bot/marketplace/bots/researchy)
34. [GTM Account Research](https://x.ai/bot/marketplace/bots/account-research)
35. [Deal Hunting](https://x.ai/bot/marketplace/bots/deal-hunting)
36. [Haggle Bot](https://x.ai/bot/marketplace/bots/haggle-bot)
37. [Alfred](https://x.ai/bot/marketplace/bots/alfred)

---

### 证据标注约定

- **已观察/官方明示**：上表“已确认”内容及官方页面展示的具体实例。
- **设计推断**：五 Bot 架构、目录、Routine 时间、回执格式、两周 PoC 是依据产品原语提出的建议，并非官方唯一推荐。
- **未知/未支持声明**：没有官方证据的管理 API、调度 SLA、金融连接器、交易可靠性、记忆/存储定量上限均未当作已有能力。
