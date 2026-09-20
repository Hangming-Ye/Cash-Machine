# 金融 AI Agent 应用架构调研：给 Grok Bot 投资研究工作流的可复用设计

> 调研日期：2026-09-20。范围为 12 个有实质实现或论文支撑的开源项目；重点源码下钻 TradingAgents、ai-hedge-fund、Dexter、FinMem，并交叉核对 Agent Rita、FinRobot。本文只提取架构模式，不复用代码。项目自报收益、排名和回测结果均未在本次调研中复现。

## 结论

不建议为了“Chief 不会规划”再引入一套新的 Agent 编排平台。Grok Bot 已经提供常驻云电脑、Routine、共享文件和移动端接管，缺的不是另一个总控，而是**确定性的研究状态机、结构化交接和硬约束**。

首版可保留一个 Chief，但把它降级成“路由与汇总器”：它只能从固定任务模板中选下一步、检查回执是否齐全、输出用户待决策项；选股、估值、仓位和记忆更新由专门工具或规则完成。对弱模型而言，这比让 Chief 自由拆解任务可靠得多。

## 六条核心架构建议

### 1. 用固定研究状态机约束 Chief，不让它自由规划

每个标的只允许沿以下状态推进：

`DISCOVERED → SCREENED → RESEARCHING → REVIEW_READY → WATCH / BUY_ZONE / HOLD / TRIM / EXIT / REJECTED`

每次转移必须满足机器可查的门槛，例如来源齐全、数据未过期、估值场景已生成、反证已填写。Chief 只负责选择模板和汇总，不得自行跳过门槛，也不得把“几个 Agent 都同意”当作通过。

TradingAgents 的 LangGraph 固定了分析、牛熊辩论、交易与风险节点，但源码也显示一次标的会经历多轮相似模型调用；这适合研究实验，不适合直接照搬成日常总控。[图结构](https://github.com/TauricResearch/TradingAgents/blob/2d17df8da1536c121e4d7395ac5a5dcec9e96d6f/tradingagents/graph/setup.py) [路由轮数](https://github.com/TauricResearch/TradingAgents/blob/2d17df8da1536c121e4d7395ac5a5dcec9e96d6f/tradingagents/graph/conditional_logic.py)

### 2. 公司发现采用“宽筛 → 供应链扩展 → 少量深研”的漏斗

每日 Routine 先用便宜、确定性的筛选器处理大股票池，只把少量候选交给模型：

1. **宽筛**：市值、收入增速、毛利率、ROIC、估值、成交量、价格动量、盈利修正等数值条件。
2. **供应链扩展**：从公告、10-K/20-F、业绩会、分部收入和客户集中度中抽取 `公司—关系—公司/产品—证据—as_of`。关系至少区分供应商、客户、替代品、设备商、渠道、原材料、地域产能。
3. **早期公司排序**：按“上游需求变化 × 收入暴露 × 产能约束 × 估值 × 证据新鲜度”排序；只有前 N 名进入深研。
4. **深研**：核验关系、财务承接能力、估值与反证，不重复全市场搜索。

Dexter 已实现自然语言转数值筛选、公司分部和 SEC/持仓工具；AlphaAgent 明确采用“候选池 → 便宜量化过滤 → 昂贵 Agent 尽调 → 规则入场”的漏斗。这两个模式可借鉴，但本次项目中没有发现成熟、通用的供应链知识图谱，因此供应链扩展仍需自己建立事实表，不能靠模型记忆猜关系。[Dexter 股票筛选](https://github.com/virattt/dexter/blob/ecaed3011f24ea24ef687ab536aa7f22f7294038/src/tools/finance/screen-stocks.ts) [分部数据](https://github.com/virattt/dexter/blob/ecaed3011f24ea24ef687ab536aa7f22f7294038/src/tools/finance/segments.ts) [AlphaAgent](https://github.com/kamendula/AlphaAgent)

### 3. 单股研究产出“因子证据包”，价格只给场景区间

每个标的维护一份可重复计算的快照，而不是一篇自由发挥的长报告：

- 质量：ROIC、毛利/经营利润率、现金转化、杠杆；
- 增长：收入、EPS、FCF、订单/产能、分部变化；
- 估值：历史与同业倍数、DCF/反向 DCF；
- 市场：趋势、波动、成交量、盈利修正；
- 催化剂与反证：事件、证据 URL、发布时间、失效条件；
- 数据状态：`as_of`、来源、缺失、冲突、是否复权/重述。

“合理价格”应输出悲观/基准/乐观三组**区间**，同时给出假设和敏感性，不输出一个貌似精确的目标价。计算由脚本完成，LLM 只解释假设与风险。Dexter 的 DCF Skill 已要求 WACC/永续增长敏感性和 sanity check；FinRobot 将数据源、定量分析、图表和报告函数分层，适合作为工具分层参考。[Dexter DCF](https://github.com/virattt/dexter/blob/ecaed3011f24ea24ef687ab536aa7f22f7294038/src/skills/dcf/SKILL.md) [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)

### 4. 持仓与观察列表使用统一动作契约，风险规则置于模型之后

每条结论统一为：

```yaml
symbol: NVDA
status: WATCH | BUY_ZONE | ADD | HOLD | TRIM | EXIT | REJECTED
price_zone: {low: null, high: null, currency: USD}
thesis: []
evidence_refs: []
invalidation: []
next_review_at: null
data_as_of: null
confidence: low | medium | high
```

模型可以提出观点和区间，但不能决定最终仓位。仓位上限、组合总敞口、行业集中度、最大亏损、数据过期和输入缺失必须由确定性规则处理。ai-hedge-fund 的实现将 `Signal` 与仓位构建分开，并在 LLM 之后用纯函数强制单股和总敞口上限，所有 clamp 都写入回执；这是本次调研中最值得直接借鉴的边界。[Signal 接口](https://github.com/virattt/ai-hedge-fund/blob/154a8b2f46dca0f40764d814e4e747b0ad71f4c4/hedge_fund/signals/base.py) [硬风险限制](https://github.com/virattt/ai-hedge-fund/blob/154a8b2f46dca0f40764d814e4e747b0ad71f4c4/hedge_fund/risk/limits.py) [单周期审计记录](https://github.com/virattt/ai-hedge-fund/blob/154a8b2f46dca0f40764d814e4e747b0ad71f4c4/hedge_fund/pipeline/models.py)

### 5. 决策复盘采用不可变账本，记忆只保存规则和已结算教训

每次用户决策写一条不可变记录：当时数据、建议、用户选择、价格区间、证据、反证、失效条件。到预定日期再补写结果、基准超额收益、判断失误类型和可复用教训；不要覆盖原结论。

TradingAgents 当前决策日志已经区分 pending/resolved，使用 `(ticker, trade_date)` 防重，并按“结果实际可知日期”过滤历史教训，避免回测时偷看未来。FinMem 的短/中/长期和反思记忆展示了衰减、重要度、反馈和层级迁移，但其收益主张来自论文实验，且复杂记忆打分不应先于一份可审计账本。[TradingAgents 决策日志](https://github.com/TauricResearch/TradingAgents/blob/2d17df8da1536c121e4d7395ac5a5dcec9e96d6f/tradingagents/agents/utils/memory.py) [FinMem MemoryDB](https://github.com/xt2201/finmem/blob/a6fb1fe9d2947023397ba3c6d5746049c4e432e2/puppy/memorydb.py)

应分开保存三类内容：用户长期偏好；带 `as_of` 的易变事实；决策及后来结果。只允许第三类中已经结算、能指出证据的教训进入下次提示。

### 6. 对弱模型和成本设置硬预算，并保持只读研究边界

- 每个 Routine 固定最多候选数、模型轮数、工具调用数、输出字符数和预算；超限交付“部分完成”。
- 宽筛和计算走代码；只有幸存候选才调用模型。相同标的/日期/输入哈希命中缓存。
- 最多保留 2–3 个真正信息源不同的专员，例如“基本面”“事件/供应链”“组合风险”。同一模型、同一数据、不同角色提示产生的共识是**相关意见**，不是三份独立证据。
- 总控只读取结构化回执；缺失就标缺失，不自行补写。
- Grok Bot 只生成研究、观察状态和订单草稿。首版不连接可写券商接口；实盘下单、撤单和资金动作继续由人完成。

Dexter 默认最多 10 次 Agent 迭代，并把单次大工具结果落盘、限制每轮工具结果总量；Agent Rita 设 3 个外层循环、每轮 15 个内部步骤并记录 token、缓存命中率和估算成本。这些是比“多加一个 Chief”更有效的弱模型护栏。[Dexter Agent loop](https://github.com/virattt/dexter/blob/ecaed3011f24ea24ef687ab536aa7f22f7294038/src/agent/agent.ts) [工具结果预算](https://github.com/virattt/dexter/blob/ecaed3011f24ea24ef687ab536aa7f22f7294038/src/utils/tool-result-budget.ts) [Agent Rita loop](https://github.com/OpenBB-finance/agent-rita/blob/f673c1fbeeeedfdbf4a253031d85eb8e96538924/src/agent/loop.ts)

## 12 个项目的架构筛选

| 项目 | 主要架构/价值 | 对 Grok Bot 可取与不可取 | 许可证 |
|---|---|---|---|
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | LangGraph 串行分析师、牛熊辩论、风险辩论、组合经理；有 checkpoint、时点数据和决策日志 | 取状态图、时点约束、可结算决策日志；不照搬多轮角色扮演 | Apache-2.0 |
| [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 统一 `Signal`，策略混合后由确定性风险层 clamp，再生成订单与完整 CycleRecord | 取“观点/仓位/风险/执行”分层和完整回执；其持久账本、paper/live broker 仍有路线图项 | MIT |
| [Dexter](https://github.com/virattt/dexter) | 单 Agent 工具循环、金融工具、Skill、混合记忆检索、权限、cron、上下文和结果预算 | 取筛选/分部/DCF Skill、预算、持久工作区；不把自由 Agent loop 当交易执行器 | README 声明 MIT；本次提交未见根目录 LICENSE，复用前需核实 |
| [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 数据源、金融函数、Agent 工作流、报告生成分层；V0 AutoGen，V1 equity research | 取金融工具层和报告流水线；V2 页面产品源码尚未开放，不能把其能力当可复用实现 | Apache-2.0 |
| [FinMem](https://github.com/xt2201/finmem) | 短/中/长期/反思记忆，按相似度、时效、重要度检索并用反馈迁移 | 取“结果反馈后再更新记忆”；先做不可变账本，再考虑复杂衰减 | MIT |
| [RD-Agent](https://github.com/microsoft/RD-Agent) | Research 提想法、Development 实现、实验反馈循环；量化场景联合进化因子与模型 | 适合离线因子研发，不适合作为每日投资总控；项目自报绩效需单独复现 | MIT |
| [TradeMaster / FinAgent](https://github.com/TradeMaster-NTU/TradeMaster) | 多模态市场情报、记忆、双层反思、工具与决策模块；与 RL 交易环境结合 | 取多模态输入与反思分层；训练/回测体系重，不适合首版个人研究工作流 | Apache-2.0 |
| [OpenBB Agent Rita](https://github.com/OpenBB-finance/agent-rita) | 薄 harness；模型选工具；本地 SQL 处理已加载表格；Workspace 通过 SSE/MCP 回传数据；原生引用 | 取“薄核心 + MCP 能力 + 数据留在工具侧 + 引用”；依赖 OpenBB Workspace。Rita 为 MIT，OpenBB Platform 本体为 AGPL-3.0 | MIT（依赖边界另核） |
| [LangAlpha](https://github.com/ginlix-ai/langalpha) | 持久研究工作区、PTC 代码处理大数据、MCP、Skill、异步子 Agent、自动化与证据面板 | 架构完整，可借鉴“代码处理原始数据，只回传摘要”；对本项目过重，不应替换 Grok Bot | Apache-2.0 |
| [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 金融数据、指令微调与金融模型生态，重点是模型/数据而非完整个人投资工作流 | 可作为领域模型或情绪/抽取组件候选；不能解决总控、组合和审计问题 | MIT |
| [Qlib](https://github.com/microsoft/qlib) | 数据、特征、模型、回测、实验记录的量化研究平台；支持 point-in-time 数据 | 适合作为离线因子与回测底座；不需要把其整套平台塞进 Grok Bot 首版 | MIT |
| [AlphaAgent](https://github.com/kamendula/AlphaAgent) | 候选池、便宜量化过滤、Agent 尽调、规则入场；PIT-Guard；收益回测排除 LLM | 漏斗和“研究判断/机械回测”分离非常契合；项目仍是 pre-alpha、提交和用户验证很少 | MIT |

## 推荐落地到 Grok Bot 的最小版本

保留现有 Grok Bot 平台能力，只增加共享目录中的 5 个确定性 Artifact：

1. `universe/candidates.jsonl`：宽筛和供应链扩展结果；
2. `entities/{ticker}/factor_snapshot.json`：单股因子、证据与数据时点；
3. `entities/{ticker}/valuation.json`：三场景价格区间及假设；
4. `portfolio/actions.jsonl`：持仓/观察列表的统一动作契约；
5. `decisions/ledger.jsonl`：原始决定、用户选择、后续结果和复盘。

Routine 只编排这些 Artifact：晨间发现新增候选，事件触发更新相关标的，周末结算到期决策并复盘。移动端只承担查看、批准“加入观察/更新状态”和人工下单。这样能直接利用 Grok Bot 的共享云电脑、Routine 和移动端，无需维护第二个编排系统。

## 对主架构草案的直接吸收清单

与根目录 `FINANCIAL_RESEARCH_ARCHITECTURE_20260920.md` 对照后，建议把开源经验落到现有模块，而不是新增平台：

| 主架构现有模块 | 可直接吸收的实现模式 | 暂不吸收 |
|---|---|---|
| 幕僚长、任务状态 | TradingAgents 的显式图路由 + Agent Rita/Dexter 的循环上限；把研究模板和验收门槛写成状态转换 | 开放式自由规划、无上限反思 |
| 数据与证据管家 | AlphaAgent/Qlib 的 point-in-time 边界；Agent Rita 的“数据留在工具侧、引用随结果返回” | 让 Bot memory 充当行情或财报库 |
| 产业链与公司研究 | Dexter 的宽筛/分部/公告工具；用自建关系事实表补上其缺失的供应链层 | 再建一批永久行业角色反复读同一新闻 |
| 单票量化研究 | Qlib/RD-Agent 仅用于离线、限预算的因子实验；AlphaAgent 将机械回测与 LLM 评议分开 | 让 LLM 参与收益证明或自动扩大搜索空间 |
| 持仓/自选与风险复核 | ai-hedge-fund 的统一 Signal、确定性风险 clamp、CycleRecord；先产出条件动作，再由人工下单 | live broker、模型决定仓位、Agent 自动执行交易 |
| 判断台账与经验沉淀 | TradingAgents 的 pending/resolved 与 known-at 过滤；FinMem 只作为后续检索/衰减参考 | 覆盖旧判断、按一次盈亏自动强化 prompt |

因此主架构中的六职责可以保留，但运行时应按任务只唤醒必要职责；“角色”是责任边界，不应默认变成六次模型调用。

## 证据边界与许可证说明

- 本次只读取公开 README、许可证和少量关键实现文件，没有运行项目、接入付费数据源或复现回测。
- TradingAgents、RD-Agent、FinAgent、FinMem 等论文或 README 中的收益与优于基准声明均是作者报告，不能作为本项目预期绩效。
- 多 Agent 角色数量、辩论轮数和“共识”不构成统计独立性；独立性来自不同来源、不同计算方法和可复查证据。
- 架构描述通常不受代码许可证限制；若复制实现代码，仍需逐项目遵守许可证。尤其 Dexter 当前检出的提交中 README 写 MIT，但根目录没有 LICENSE 文件；OpenBB Agent Rita 为 MIT，而 OpenBB Platform 本体是 AGPL-3.0，应按实际集成边界单独审查。

### 本次源码快照

- TradingAgents `2d17df8da1536c121e4d7395ac5a5dcec9e96d6f`
- ai-hedge-fund `154a8b2f46dca0f40764d814e4e747b0ad71f4c4`
- Dexter `ecaed3011f24ea24ef687ab536aa7f22f7294038`
- FinMem `a6fb1fe9d2947023397ba3c6d5746049c4e432e2`
- Agent Rita `f673c1fbeeeedfdbf4a253031d85eb8e96538924`
- FinRobot `6d6ccd32c1b8b1904dc656cf06897438aba3daec`
