# 金融 Agent Prompt 源码审计：把“角色”改成 Grok 可执行任务

> 调研日期：2026-09-20。重点不是再列项目，而是下钻真实 prompt 与相邻控制流，提取适合 Grok 4.5/4.6 的任务卡。共检查 7 个主体项目，并额外核对一个同名 Serenity 实现以排除来源混淆；实际阅读了 TradingAgents、Dexter、RD-Agent、muxuuu/serenity-skill 的 prompt 正文，并核对 FinRobot、Agent Rita、ai-hedge-fund 的运行边界。未复制第三方长提示词。

## 先给结论

当前六角色描述不足以指导弱模型工作，因为它只回答“你是谁”，没有回答“本轮要查哪一个可证伪问题、先调用什么、缺什么就停、交什么机器可验收结果”。

Grok Bot 中应同时存在两层提示：

1. **角色常驻提示**：只放权限、禁区、可用任务类型、统一回执协议，控制在短篇幅。
2. **任务实例提示**：由程序按场景生成，带确定输入、步骤、工具白名单、输出 schema、停止条件和失败分支。

复杂步骤应写入程序状态机，不能靠 system prompt 要求模型“记住”。模型适合提出问题、归纳证据、比较解释；日期、金额、口径、估值算术、去重、门禁、状态迁移和重试上限都应由程序执行。

对 Grok 4.5/4.6 最有用的源码经验不是角色扮演，而是四种约束：TradingAgents 的工具顺序与状态字段、Dexter 的工具预算与 Skill 路由、RD-Agent 的“假说—代码—运行—反馈”闭环、muxuuu/serenity-skill 的“先层后公司”与证据分级。muxuuu 仓库本身不提供研究采集器，因此不能把“脚本先行”归给它。

## 源码矩阵

| 项目与场景 | 实际 prompt 文件 / 快照 | Prompt 要模型回答的领域问题 | 必需输入与工具 | 输出与停止 | 程序负责什么 | 对本项目判断 |
|---|---|---|---|---|---|---|
| TradingAgents：基本面报告 | [`fundamentals_analyst.py`](https://github.com/TauricResearch/TradingAgents/blob/2d17df8da1536c121e4d7395ac5a5dcec9e96d6f/tradingagents/agents/analysts/fundamentals_analyst.py)；提交 `2d17df...` | 公司财务、报表、历史表现中哪些信息影响交易判断 | ticker、交易日、公司身份；fundamentals、资产负债表、现金流、利润表工具 | 无 tool call 时把文本写入 `fundamentals_report`；有 tool call 则图继续 | LangGraph 保存状态、绑定工具、决定下一节点 | **Adapt**：保留确定 ticker/date/tool；拒绝“尽可能详细”这类无边界要求；改成一组财务问题与缺失状态 |
| TradingAgents：技术市场报告 | [`market_analyst.py`](https://github.com/TauricResearch/TradingAgents/blob/2d17df8da1536c121e4d7395ac5a5dcec9e96d6f/tradingagents/agents/analysts/market_analyst.py)；同提交 | 当前趋势和波动如何，哪些指标互补 | 先取价格 CSV，再取最多 8 个指标；最终取 verified snapshot | 最终表格报告；精确价格必须服从 verified snapshot | 工具调用顺序、快照冲突处理、图节点循环 | **Adapt**：把“最多 8 个指标”再收缩到任务注册的 1–2 个；verified snapshot 很值得保留 |
| TradingAgents：牛熊辩论及最终决策 | [`bull_researcher.py`](https://github.com/TauricResearch/TradingAgents/blob/2d17df8da1536c121e4d7395ac5a5dcec9e96d6f/tradingagents/agents/researchers/bull_researcher.py)、[`conditional_logic.py`](https://github.com/TauricResearch/TradingAgents/blob/2d17df8da1536c121e4d7395ac5a5dcec9e96d6f/tradingagents/graph/conditional_logic.py) | 牛方反驳熊方，经理在 BUY/HOLD/SELL 中裁决 | 四份分析报告、辩论历史、对手上一轮、最大轮数 | 达到轮数或经理输出后停止 | 程序计轮、路由到经理 | **Reject 默认启用**：首轮对手文本可能为空仍被要求反驳，容易编造对方观点；多轮成本高且不增加独立证据 |
| Dexter：通用金融研究 Agent | [`src/agent/prompts.ts`](https://github.com/virattt/dexter/blob/ecaed3011f24ea24ef687ab536aa7f22f7294038/src/agent/prompts.ts)；提交 `ecaed30...` | 用户的金融问题该调用哪些工具或 Skill | 当前日期、紧凑工具描述、Skills metadata、用户规则、记忆；大结果可落盘 | 直接回答或有限工具循环；按渠道压缩格式 | 工具 registry、结果截断/落盘、最大迭代、子任务隔离、预算 | **Reuse 方法**：常驻 prompt 只做路由；工具描述承担能力说明；子任务必须附完整上下文 |
| Dexter：DCF | [`src/skills/dcf/SKILL.md`](https://github.com/virattt/dexter/blob/ecaed3011f24ea24ef687ab536aa7f22f7294038/src/skills/dcf/SKILL.md)；提交 `ecaed30...` | 历史 FCF 如何推演，WACC/永续增长如何影响价值 | 3–5 年财务、股本、净债务、预测假设、当前价；金融数据工具和计算 | 假设、预测、WACC、终值、权益桥、敏感性、牛基熊、风险 | 理想边界应由计算代码生成每个单元格与校验；原 Skill 仍给模型较多算术负担 | **Adapt**：保留问题顺序和 sanity checks；计算全部移到程序，模型只给假设依据与解释 |
| RD-Agent：因子研发 | [`qlib/prompts.yaml`](https://github.com/microsoft/RD-Agent/blob/35cfc19/rdagent/scenarios/qlib/prompts.yaml)、[`quant_experiment.py`](https://github.com/microsoft/RD-Agent/blob/main/rdagent/scenarios/qlib/experiment/quant_experiment.py)、[`quant.py`](https://github.com/microsoft/RD-Agent/blob/main/rdagent/app/qlib_rd_loop/quant.py)；该 prompt 文件最近变更 `35cfc19` | 上轮实验说明了什么；下一条因子假说与实现任务是什么 | 数据集说明、运行环境、接口、输出格式、模拟器、历史实验和反馈 | JSON 实验任务；代码运行结果；feedback；循环到预算或停止 | 实际代码生成、隔离运行、指标计算、实验 trace、并行上限 | **Reuse 闭环，Reject 搜索自由度**：P1 只允许从注册因子模板选择，不能让 Grok 自动扩搜索空间 |
| muxuuu/serenity-skill：产业链研究方法 | [`SKILL.md`](https://github.com/muxuuu/serenity-skill/blob/main/SKILL.md)、[`research-prompt-pack.md`](https://github.com/muxuuu/serenity-skill/blob/main/assets/research-prompt-pack.md)、[`deep-research-workflow.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/deep-research-workflow.md)、[`validate_skill.py`](https://github.com/muxuuu/serenity-skill/blob/main/scripts/validate_skill.py)；当前 `main` 于 2026-09-20 逐文件核对；早期 prompt pack 可追溯到提交 [`d23e6e4`](https://github.com/muxuuu/serenity-skill/commit/d23e6e4b5125daaf1b4d56ddf15b56faa96e497d)，但当前树已变化 | 需求如何沿系统传到稀缺层；公司处在哪个验证/量产/收入阶段；什么证据会推翻 | 主题、市场、时间窗或 ticker；宿主提供搜索、浏览器、公告/财报和行情能力 | 先排层级，再给公司研究优先级、证据强弱、反方理由和下一步核验；证据不足允许少给候选 | 当前脚本只有维护用 `validate_skill.py`，只检查 Skill 结构，不抓数据；采集、实体解析、估值和状态跟踪必须由本项目程序实现 | **Adapt 主体方法**：先层后公司、阶段成熟度、证据阶梯、证伪；prompt pack 只是入口示例；不采用过时的 local scorecard 入口，也不把来源数/候选数当完成门槛 |
| olaxbt/serenity-skill：脚本化研究应用（同名但独立） | [`README.md`](https://github.com/olaxbt/serenity-skill/blob/main/README.md)、[`SKILL.md`](https://github.com/olaxbt/serenity-skill/blob/main/SKILL.md)、[`agent_prompt.py`](https://github.com/olaxbt/serenity-skill/blob/main/serenity_twin/agent_prompt.py)、[`live_research.py`](https://github.com/olaxbt/serenity-skill/blob/main/scripts/live_research.py)、[`radar.py`](https://github.com/olaxbt/serenity-skill/blob/main/scripts/radar.py)；独立仓库 `main` 于 2026-09-20 核对 | corpus 中某 ticker 的历史观点是否仍有效；当前行情/新闻/SEC 是否改变结论；关注热度如何变化 | 自带 corpus、ticker lookup、live research、radar，并依赖其可选网络/API 配置 | 区分 corpus view、live verification、research map；脚本结果先于 LLM 叙述 | 该仓库才拥有 lookup/live/radar、陈旧检查、结构化 JSON 和浏览器 UI | **仅作来源边界对照**：这些能力不得归给 muxuuu，也不作为本主体架构的 Serenity 复用来源；若以后评估其代码，应单独做依赖、许可和数据质量审计 |
| FinRobot Equity：八段研报 | [`text_generator_agents.py` 所在目录与 8 个 section agents](https://github.com/AI4Finance-Foundation/FinRobot/tree/6d6ccd32c1b8b1904dc656cf06897438aba3daec/finrobot_equity/core/src/modules)；提交 `6d6ccd...` | 投资概览、估值、风险、竞品等各段如何叙述 | FMP 财务、预测 CSV、比率 CSV、同行数据 | 多个 section 文本文件，再由 HTML/PDF renderer 组合 | 财务处理、预测、图表、文件编排先完成，Agent 写分段文字 | **Reuse 分层**：数值先算、叙述后写；不复用“8 个 Agent 等于 8 个独立判断”的表象 |
| Agent Rita：工作区数据问答 | [`src/agent/prompt.ts`](https://github.com/OpenBB-finance/agent-rita/blob/f673c1fbeeeedfdbf4a253031d85eb8e96538924/src/agent/prompt.ts)、[`loop.ts`](https://github.com/OpenBB-finance/agent-rita/blob/f673c1fbeeeedfdbf4a253031d85eb8e96538924/src/agent/loop.ts)；提交 `f673c1...` | 应找哪个 widget、是否拉数据、何时用 SQL/外部工具 | 当前 widgets、tool schema、已加载表格、用户问题 | 文本、表格、artifact、引用；外层最多 3 轮，每轮有限步骤 | SQLite、表解析、引用聚合、SSE 往返、工具注册、循环上限 | **Reuse 薄 prompt**：能力写进工具 schema；但自由选工具只适合探索问答，不适合风险门禁 |
| ai-hedge-fund：投资人格与仓位 | [`hedge_fund/`](https://github.com/virattt/ai-hedge-fund/tree/154a8b2f46dca0f40764d814e4e747b0ad71f4c4/hedge_fund)、[`risk/limits.py`](https://github.com/virattt/ai-hedge-fund/blob/154a8b2f46dca0f40764d814e4e747b0ad71f4c4/hedge_fund/risk/limits.py)；提交 `154a8b...` | 按投资大师原则把指标压成 buy/sell/hold 与 confidence | 规则算出的指标、当前仓位、其他 Agent signals | 固定 signal/confidence/reasoning；随后风险层 clamp | 仓位、总敞口、限制原因、CycleRecord 由代码产生 | **Reuse 风险后置，Reject 人格投票**：哲学 prompt 可作检查清单，不能把任意阈值或信心分当证据 |

## 从真实 prompt 看出的五类失败

### 1. 角色说明没有任务边界

“你是产业链研究员”“你是风险经理”只影响语气，不能告诉模型本轮应回答什么。

TradingAgents 的基本面 prompt 要“全面、详细、可行动”，却没有限定报告期、同业、关键指标、数据缺失处理或价值驱动树。弱模型很容易把工具返回改写成长报告，而不是关闭一个决策问题。

本项目角色提示只保留：允许接收的 `task_type`、可用工具、禁止动作、统一回执。具体问题必须来自任务模板。

### 2. 强制 BUY/HOLD/SELL 会把信息不足伪装成判断

TradingAgents 和投资人格项目都把最终输出压进交易标签。仅从这种固定 schema 就能看出一项设计风险：若没有独立的“证据不足/数据陈旧”状态，HOLD 可能同时表示中性判断、维持已有仓位或无法判断。这里讨论的是输出契约风险，不据此声称公开项目已经发生特定实现故障。

本项目必须把两条轴分开：

- `research_state = supported | contradicted | mixed | insufficient | stale`
- `action_view = buy_zone | hold | trim | exit | watch | none`

当研究证据不足或影响论点的数据陈旧时，程序把 `research_state` 设为 `insufficient` 或 `stale`，并禁止依赖该缺口的执行动作。若只有券商持仓、账户规模或用户风险参数未知/过期，则只阻断账户级 `ADD/TRIM/EXIT` 和仓位数量；标的级研究仍可输出 `buy_zone/watch/hold_thesis` 等意见，并显式标注“不是账户动作”。

### 3. 任意 score / confidence 没有统计含义

投资人格 prompt 常让模型返回 0–100 confidence；muxuuu 早期 prompt pack 也残留 local scorecard 入口，但当前主方法已强调用证据和推理解释优先级。任意把多个定性维度相加仍没有统计含义：既无校准集，也没有解释 70 与 80 的实际差异。

本项目不用单一信心分。改为四个可检查字段：`evidence_completeness`、`source_quality`、`thesis_status`、`uncertainty_reasons[]`。若以后要概率，必须来自有标签历史集的校准，而不是 prompt 自报。

### 4. Prompt 声称有工具，运行环境却没有

muxuuu/serenity-skill 要求在当前事实问题上优先使用宿主的搜索、浏览器、公告/财报和行情工具，但它不捆绑采集器；当前唯一脚本 `validate_skill.py` 也不联网。若把 prompt pack 直接粘到 Grok 子 Bot，却未从运行时注册这些宿主工具，模型可能把“请联网核验”写成已经执行。`live_research.py`、ticker lookup 和 radar 属于独立的 olaxbt/serenity-skill，不能据此补足 muxuuu 的运行能力。Dexter 动态插入实际工具描述的做法更适合本项目。

任务生成器只能从运行时工具 registry 选工具；工具不存在就把任务改成 `needs_capability`，输出缺口，不把工具名留在提示里诱发幻觉。

### 5. 辩论把上下文和成本变大，却没有新证据

TradingAgents 牛熊双方读取相同四份报告，只因角色不同而争论；首轮甚至可能收到空的“对方上一轮”。这会制造措辞分歧，不能制造统计独立性。

本项目的独立复核应换成固定检查：重新打开最高影响的 3 条原始证据、重算 3 个关键数、提出至少一个替代解释、检查持仓约束。只有发现新证据或计算错误才退回，不进行多轮修辞辩论。

## 适合 Grok 4.5/4.6 的提示结构

### 常驻 system prompt：所有专员共用骨架

```text
你只执行收到的 task_type，不自行扩展目标。
只使用 runtime_tools 中实际存在的工具；每条事实引用 evidence_id。
金额、日期、单位、估值和状态门禁以程序结果为准，不心算覆盖。
缺输入时返回 needs_data；工具缺失返回 needs_capability；证据冲突返回 mixed。
完成时只输出指定 JSON。不得下单，不得把缺数据写成 HOLD。
```

角色差异只追加 5–8 行，例如“产业链研究只能处理 `theme_map / candidate_verify / profit_bridge`；不得给组合仓位”。不要写长篇人格、自我介绍或投资大师故事。

### 每次任务 prompt：程序生成 9 个区块

```yaml
task_id: SC-20260920-001
task_type: candidate_verify
decision_question: "AXTI 是否已从送样进入可验证认证阶段？"
cutoff_at: "2026-09-20T08:00:00+08:00"
inputs: {entity_ids: [], snapshot_ids: [], prior_decision_id: null}
required_questions: []
allowed_tools: []
steps: []
output_schema: "candidate_verify.v1"
stop_conditions: []
budget: {tool_calls: 6, sources: 8, retries: 1}
```

`required_questions` 必须是金融问题，不是“做深入分析”。`steps` 必须可观察；每一步都有程序验收。

## 六角色应改成哪些实际任务卡

### 幕僚长：只做模板选择与缺口关闭

**输入**：用户目标、最新持仓/自选快照状态、未结任务、事件日历、预算。

**领域问题**：今天哪一个变化可能改变判断；需要哪几份独立产物；哪些可以并行；什么结果足以结案。

**固定步骤**：

1. 程序列出 eligible templates 与触发原因。
2. Grok 只从模板中选择，不自由发明节点。
3. 程序展开 DAG、校验依赖、分配 owner 和预算。
4. Grok 对失败节点只选 `retry_same / retry_alt_source / degrade / close_insufficient`。
5. 程序核对回执齐全后，Grok 写变化摘要。

**停止**：全部必需节点完成；或关键输入缺失且替代源已用尽；或预算到顶。

**输出**：`research_plan.v1`，不得直接生成投资观点。

### 数据与证据管家：处理一条主张，不写报告

**输入**：实体 ID、cutoff、需要的字段/文档、来源优先级、已有证据 hash。

**领域问题**：该值/陈述在 cutoff 前是否可知；来自原始披露还是转述；是否与旧版本冲突。

**固定步骤**：实体解析 → 原始源优先取数 → 保存时间与口径 → 同事件去重 → 标 fresh/stale/partial/conflict。

**程序**：下载、hash、字段类型、币种、修订版本、转载聚类、PIT 门禁。

**输出**：`evidence_receipt.v1`；每条 claim 只能引用已存在 evidence_id。

### 产业链研究：拆成三个任务，禁止一次写完大报告

`theme_map` 回答需求冲击、单位用量、8 层链条和候选瓶颈；`candidate_verify` 回答公司是否真实暴露、当前成熟度、客户/替代/扩产证据；`profit_bridge` 回答销量×价格×份额如何进入收入、毛利、FCF。

每个候选必须回答：产品是什么、当前处于研发/送样/认证/量产/订单/收入哪一阶段、证据日期、下一个可观察事件、哪个事实会否定。

程序计算估值场景和单位经济，不让 Grok 自报目标价。早期证据不足可输出 `lead_only`；不能为了凑候选给 BUY。

### 市场与事件研究：先做事件簇，再解释预期差

**问题**：这是新事实、管理层展望、分析师观点还是社交传播；它相对上次到底改变了什么；价格反应是否超出历史事件分布。

程序先聚类转载、提取发布时间与作者、关联行情窗口。Grok 只填写事实摘要、观点方向、替代解释和对 thesis 的影响。

输出 `event_cluster.v1`，分开 `fact_change / expectation_change / price_change`，禁止把社交热度当事实可信度。

### 单票量化研究：采用 RD-Agent 闭环，但候选由 registry 限死

**问题**：例如“财报跳空后等待 3 日是否比次日追涨改善 20 日最大不利变动”。

程序冻结标签、成交时点、基准、成本、fold 和候选参数；Grok 只能选择已注册的 `trend_confirm / drawdown_risk / post_event_wait` 实验。

程序运行、计算 OOS 指标、覆盖率和失败原因。Grok 解释结果与适用状态，不生成新参数继续试。

停止条件为：注册实验跑完、达到尝试预算、有效样本不足或无增量。输出 `factor_experiment.v1`，允许 `no_stable_increment`。

### 风险与独立复核：检查表代替辩论

**输入**：原始 evidence 包、程序估值结果、因子卡、持仓与约束快照。

**必查问题**：ticker/币种/股本是否一致；三项关键数是否可重算；是否存在时点穿越；主要反证是否被处理；动作是否违反敞口或数据新鲜度门禁。

程序先跑硬门禁，Grok 只能给 `pass / return_with_issues / block`，每个 issue 指向字段和 evidence_id。不得用“多数 Agent 同意”放行。

## 三个端到端金融场景

### 场景 A：发现供应链早期公司

`program trigger` 发现资本开支/架构变化 → `theme_map` 给瓶颈层 → 程序扩展实体与官方披露 → 多个 `candidate_verify` 并行 → 仅成熟候选进入 `profit_bridge` → 估值程序生成三场景 → 风险复核 → Chief 输出“早期线索 / 可投资研究 / 被否定”三类卡。

若只有社交帖、没有公司/客户披露，流程停在 `lead_only`；这就是完成，不继续逼模型补齐故事。

### 场景 B：财报后更新持仓判断

程序锁定财报版本、行情和持仓 cutoff → 基本面任务只比较上次假设与实际 → 事件任务拆 guidance 与市场预期 → 估值程序重算区间 → 因子任务读取已登记的事件后等待信号 → 风险门禁检查集中度 → Chief 只总结“什么变了、什么没变、何时改判”。

如果券商快照过期，可以更新标的研究状态，但程序禁止输出账户级 ADD/TRIM。

### 场景 C：单票因子是否值得保留

用户登记一个决策问题 → 程序生成冻结实验协议 → Grok 检查问题是否可检验 → 程序回测与滚动 OOS → Grok 对失败作金融解释 → 程序保存全部尝试 → 达到门槛才进入 shadow validation。

Grok 不接触最终测试集，不决定是否扩大参数范围，也不因单次 Sharpe 高就批准上线。

## 首版该直接采用与拒绝的内容

**直接采用**：任务级 ticker/date/cutoff；runtime tool registry；先脚本后叙述；结构化回执；显式缺失状态；工具调用/来源/重试预算；程序计算；原始证据回查；实验 trace。

**适配后采用**：TradingAgents 的图路由、Dexter Skill、RD-Agent feedback、muxuuu/serenity-skill 的瓶颈链与证据阶梯、FinRobot 的分段写作。它们都需缩小自由度并接本项目 schema。olaxbt/serenity-skill 的 corpus/live/radar 实现不纳入这条复用链。

**明确拒绝**：长篇角色人格；强制 BUY/HOLD/SELL；自报 0–100 confidence；定性维度随意相加；相同数据上的多 Agent 投票；无新增证据的牛熊多轮辩论；在 prompt 中要求不存在的工具；让 LLM 算 DCF、统计检验或仓位；把“来源数/候选数够多”当完成。

## 对主体架构的具体修订建议

在六角色表之后新增 `role_prompt` 与 `task_prompt` 两层；把现有 `research_plan` 节点直接变成任务 prompt 的字段，而不是只作为文档概念。

P1 不应先写六个丰满 system prompt。先实现 6 个任务模板：`plan_run`、`evidence_fetch`、`company_delta`、`event_cluster`、`risk_review`、`publish_card`。一只持仓与一只自选连续跑 5 日后，再加 `theme_map / candidate_verify / profit_bridge`，最后加受限因子实验。

每个模板至少做三组 eval：完整输入、关键字段缺失、工具返回冲突。验收看 JSON 合法率、引用覆盖、正确弃权、重复任务是否幂等、是否越过程序门禁；不看报告长度或角色语气。

本次限制：FinRobot、Agent Rita 和 ai-hedge-fund 主要用于控制流边界核对；未逐字收录其所有 prompt。muxuuu 当前 `main` 与其初始提交的文件树已有变化，因此主体只采用 2026-09-20 逐文件核对后的研究方法，不依赖过时脚本说明；进入实现前仍应把所采用的 `SKILL.md`、workflow、evidence ladder 和 prompt pack 冻结到同一完整 SHA。olaxbt 为独立实现，仅用于证明脚本能力来源，不能替代 muxuuu 的方法源。
