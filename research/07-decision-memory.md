# 决策复盘与长期记忆设计：个人 Grok Bot 投资研究平台

> 目标：服务供应链早期投资研究和单股因子辅助；对持仓与观察名单输出 `BUY / SELL / WATCH`、有依据的价格区间与下一验证点。系统不自动交易。本文中的概率、目标价和动作均是研究假设或经校准后的统计描述，不是事实。

> **后续修订（2026-09-20）**：用户要求记忆从首版实现提炼、压缩与再注入。本文延后记忆组件、复杂规则晋升和人工闸门等建议不是已批准要求；当前取舍见 [记忆补充调研](14-memory-consolidation.md) 和 spec001。

## 结论

不要让“弱模型 Chief”拥有写入事实、改规则或直接下交易结论的权力。它只负责把经过门禁的材料组织成候选判断；事实账本、行情时间戳、计算、规则晋升和最终动作由确定性组件与人工审批控制。

最小可行设计是三种存储、两次评分、一道人工闸门：

1. **不可变历史证据库**：保存当时能看到的原文、发布时间、抓取时间、修订版本、引用位置与哈希；只能追加或建立新版本，不能被摘要覆盖。
2. **决策账本**：冻结“当时信息集、备选项、预测、反证、价格、结论与未选方案”。先做不看结果的过程评分，结果到期后再单独记表现与归因。
3. **检索记忆库**：存摘要、主题、实体、经验候选和向量索引，可修改、合并、淘汰；每条必须反向指向不可变证据或决策 ID。它没有事实权威。
4. **规则候选库**：反思只能生成候选规则。只有预注册、足够样本、时间外验证和人工批准后，才进入“批准监控规则”；不得由一次成功/失败自动晋升。
5. **人工动作闸门**：模型只能给 `BUY / SELL / WATCH / ABSTAIN` 建议；用户确认前不触发订单。输入缺失、行情过期、证据冲突或估值未完成时强制 `ABSTAIN`。

这也符合现有 Public Equity Investing 资料中的核心约束：公司基本面判断、证券价格/估值判断、仓位动作必须分离；论据按追加方式保存；阈值要标注来源与审批状态；缺少当前价格或估值输入时，证券结论不是 decision-grade。

## 参考实现与可借鉴部分

| 来源 | 可借鉴 | 不直接照搬 |
|---|---|---|
| [FinMem](https://arxiv.org/abs/2311.13743) | 分层记忆、不同时间跨度、可解释的历史检索 | 论文目标偏自动交易；回测收益不能证明适合个人基本面研究，也不能授权模型自我进化规则 |
| [FinAgent](https://arxiv.org/abs/2402.18485) | 市场信息、低层反思、高层反思分开；多类记忆检索 | 双层反思仍可能把行情结果写成“经验真理”；反思必须先进入候选区 |
| [Reflexion](https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html) | 用自然语言反馈改善下一次任务，不必微调模型 | 任务成功反馈与投资决策质量不是一回事；单次盈亏不应成为语义梯度 |
| [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | checkpoint 保存单线程执行状态，store 保存跨线程长期数据；便于暂停、恢复和人工介入 | checkpoint 是运行状态，不是审计账本；生产持久化与保留策略需另设 |
| [Mem0 Memory Types](https://docs.mem0.ai/core-concepts/memory-types) | 按 user/agent/run 做检索范围；普通记忆可 ADD/UPDATE/DELETE | 官方文档明确 semantic/episodic 类型目前未实现；可更新记忆不能承担不可变证据职责 |
| [Letta Stateful Agents](https://docs.letta.com/v1-sdk/concepts/stateful-agents) | 核心记忆、消息、工具调用持久化；上下文外历史仍可取回 | agent 可编辑自身 memory block，若用于投资事实会产生自我篡改风险 |
| [Gneiting & Raftery：严格适当评分规则](https://doi.org/10.1198/016214506000001437) | 用 Brier/log score 评价概率，促使模型报告真实信念 | 只对预先定义、可结算事件评分；不能给含糊叙述硬配概率 |
| [Baron & Hershey：Outcome Bias](https://bear.warrington.ufl.edu/brenner/mar7588/Papers/baron-hershey-jpsp1988.pdf) | 决策质量必须按当时可见信息评估；结果另记 | 不能把“涨了”倒推为 BUY 决策好，也不能把“跌了”倒推为研究错 |
| [Deflated Sharpe Ratio](https://doi.org/10.2139/ssrn.2460551) | 规则研究记录尝试次数，并对多重试验、非正态与样本长度降权 | 平台不是策略工厂；低频研究规则样本不足时应停留为提示，不输出伪精确显著性 |
| [Scaling Point-in-Time Language Models](https://www.nber.org/papers/w35247) | 说明训练语料含未来信息会破坏金融回测；需要 point-in-time 模型/材料 | 即使文档按时点切分，通用 LLM 权重仍可能知道未来；回测中必须限制模型用途或使用冻结时期模型 |

## 系统边界与决策合成

平台每次对单股只合成三层对象，禁止模型跨层偷换结论：

### 1. 公司基本面情景

围绕供应链位置、客户集中度、产能/良率、库存、订单、议价权、资本开支、现金转换和管理层可信度建立 `bear / base / bull`。每个情景包含驱动、期限、证据标签（reported / derived / analyst assumption）、可证伪阈值和对应价值区间。情景概率只有在事件定义互斥且完备、预测可结算、历史校准样本够用时才显示；否则只列情景和关键假设。

### 2. 证券价格与技术时机

把企业价值判断转换为证券的价格区间，同时明确当前报价、币种、交易所、来源和 `quote_as_of`。技术因子只回答“现在的入场/退出时机与拥挤度怎样”，不能证明公司论点。价格区间至少拆出盈利/现金流假设、估值倍数或贴现率、净债务/股本稀释和安全边际；技术信号不得单独抬高长期合理价值。

### 3. 仓位动作

动作依赖前两层以及现有仓位、成本、最大容忍损失、组合暴露和事件窗口：

- `BUY`：公司论点可检验且未破坏；证券达到用户批准的回报/安全边际门槛；报价新鲜；没有决策阻塞项。持仓时可细分 `ADD`。
- `SELL`：公司 kill criterion 已触发，或证券价格超过合理区间且风险回报恶化。持仓时细分 `TRIM`（价格/集中度问题）与 `EXIT`（论点破坏）。
- `WATCH`：方向可用但尚未达到价格、证据或催化门槛；必须带“看什么、阈值、期限、触发后的动作”。
- `ABSTAIN`：关键数据缺失/冲突、报价超时、模型无法复算、情景不完备、证据来自未来、或 Chief 输出与确定性规则冲突。UI 应把它作为正常结果，而不是异常。

`BUY / SELL / WATCH` 是面向用户的顶层标签；`ADD / TRIM / EXIT / WAIT / RE-UNDERWRITE` 是有持仓语境的动作细化。观察名单没有现有仓位时，不应写“trim/exit”。

## 最小账本

第一版不需要复杂记忆框架。用关系库保存不可变行，用对象存储保存原文快照，用普通全文/向量索引做召回即可。

### A. `evidence_event`（追加，不可覆盖）

```text
evidence_id, security_id, supply_chain_entity_id
source_url, source_type, publisher, source_published_at
retrieved_at, effective_period, available_from, revision_of
content_hash, immutable_blob_uri, exact_locator
fact_text, fact_status(reported|derived|assumption)
known_at_cutoff, ingestion_version
```

`available_from` 是回测可使用的最早时刻；不能只用财报所属季度。修订数据必须新建行并指向 `revision_of`，历史运行只看当时版本。

### B. `decision_snapshot`（追加，冻结）

```text
decision_id, security_id, created_at, decision_cutoff
portfolio_state_id, quote_price, quote_currency, quote_as_of, quote_source
company_thesis_status, security_thesis_readiness
action(BUY|SELL|WATCH|ABSTAIN), action_detail
price_range_low, price_range_base, price_range_high, horizon
assumption_set_version, model_version, prompt_version, rule_version
evidence_ids[], rejected_evidence_ids[]
options_considered[], chosen_option, rejected_options[]
reasons_for, reasons_against, disconfirming_evidence
kill_criteria[], next_proof_point, review_due_at
forecast_ids[], process_score_pre_outcome, approver, approved_at
```

`rejected_options` 必须记录当时为何没选，以及若选择它将用什么价格/时间规则评价，防止事后随意构造反事实。

### C. `forecast` 与 `resolution`

```text
forecast_id, decision_id, event_definition, resolve_by
probability, reference_class, calibration_version
status(open|resolved|void), resolution_value, resolved_at
resolution_source_ids[], brier_score
```

事件必须在决策时写成可判定陈述，例如“FY27Q2 公布的汽车业务毛利率 >= 18%”。模糊的“需求改善”不能结算，也不能进入校准统计。

### D. `review_event` 与 `lesson_candidate`

```text
review_id, decision_id, review_at
process_score_blind, outcome_return, benchmark_return
fundamental_attribution, valuation_attribution, timing_attribution
factor_market_attribution, luck_unknown, counterfactual_result
lesson_candidate_id, proposed_rule, applicable_scope
supporting_decision_ids[], contradicting_decision_ids[]
sample_n, test_protocol_id, promotion_status, approved_by
```

`process_score_blind` 由复盘者先在隐藏后续收益的界面完成，再揭示结果。归因必须允许 `luck_unknown`，不能强迫每个盈亏都有故事。

## 两阶段复盘与季度流程

### 每次决策：T0 冻结

1. 固定 `decision_cutoff`，只查询 `available_from <= cutoff` 的证据。
2. 保存当前报价及时间戳；超过市场类型配置的 freshness SLA 就强制 `ABSTAIN`。
3. 输出三层判断、所有关键假设、反证、未选方案和下一验证点。
4. 运行确定性检查并生成内容哈希；人工批准后封存。

### 证据到达：只追加

新财报、供应链验证或价格变化只新增 `evidence_event` 和新的 `decision_snapshot`。旧结论永不改写；检索摘要可以更新，但必须保留来源链。

### 每季度：先过程、后结果

1. **盲评过程**：隐藏季度收益和后见证据，按信息及时性、来源质量、替代假设、可证伪性、估值可复算、风险边界、动作一致性评分。
2. **揭示结果**：记录绝对/相对收益、最大不利变动、基本面兑现、估值变化、技术时机和组合约束。
3. **反事实复盘**：按 T0 预先登记的替代动作与执行规则计算；未预登记的反事实只作定性讨论，不计分。
4. **校准复盘**：只对已结算预测计算 Brier score，并按概率桶看 reliability；样本少时只展示原始数量和置信区间，不下“已校准”结论。
5. **规则候选**：Chief 从多条决策中提取候选，列支持与反例；不得修改线上规则。
6. **规则晋升**：人工预注册适用范围、特征、阈值、评价期、基准和失败条件；随后做时间外/滚动验证。通过后仍先以 shadow 模式运行一季，再由用户批准为监控规则。

## 可执行门禁

以下门禁应由代码计算，而不是提示词要求：

| 门禁 | 可验收条件 | 失败动作 |
|---|---|---|
| 时间完整性 | 运行读取的每条证据均满足 `available_from <= decision_cutoff`；模型调用无截止日后的检索 | 运行失败并标记 leakage |
| 报价新鲜度 | 每个建议都有 price/currency/source/quote_as_of；满足按市场配置的 SLA | `ABSTAIN`，不显示精确上行/下行 |
| 引用完整性 | 每个 reported 事实可追到 immutable blob + locator + hash | 降为未验证假设或阻塞 |
| 估值可复算 | price range 可由版本化输入和公式重算，结果与展示一致 | security_thesis=`not decision-grade` |
| 三层分离 | 公司状态、证券 readiness、仓位动作分别存在；动作引用前两层 | 阻塞发布 |
| 反证存在 | 每个 BUY/SELL 至少一个最强反方论据、kill criterion、next proof point | 降为 WATCH |
| 概率合法 | 事件互斥完备、和为 1、定义与结算日齐全；明确 assumption/calibrated | 不显示概率加权目标价 |
| 决策冻结 | 审批后 snapshot hash 不变；更正通过新版本追加 | 审计告警 |
| 过程/结果分离 | `process_score_blind` 时间早于结果揭示；UI 日志可证明隐藏 | 本次过程评分作废 |
| 规则晋升 | 有预注册 protocol、尝试次数、训练/验证切分、最小样本、反例、shadow 期和人工批准 | 只能保留 lesson candidate |
| 弱模型权限 | Chief 无证据库 UPDATE/DELETE、无规则发布、无下单工具；结构化输出经 schema 校验 | 拒绝调用或回退确定性模板 |

规则晋升的最小统计要求不宜预设一个万能数字。平台应允许按规则族配置，但必须至少报告 `sample_n`、尝试的候选规则总数、时间外表现、基准差、置信区间和跨时期稳定性。小样本供应链事件通常只能形成“研究检查项”，不能伪装成可泛化因子。

## 回测与历史重放

1. 所有查询以 `decision_cutoff` 和 `available_from` 做双时态过滤；财报期、发布日期和入库时间不能混用。
2. 训练、规则发现、阈值选择与最终评估使用严格时间顺序；同一家公司相邻季度要防止重叠标签泄漏。
3. 保存每次试验，包括被拒绝规则；报告总试验次数，避免只留下赢家。
4. 通用 LLM 可能在预训练中见过未来。严格历史重放时，优先使用 point-in-time 模型；若没有，LLM 只能抽取已提供材料、不得凭参数知识补事实，并把结果标为“叙事辅助回放”，不能作为预测能力证据。
5. 因子只使用当时可获得的成分股、财务修订版本、汇率和公司行动；包含退市样本，避免幸存者偏差。
6. 交易假设包含信号可用时刻、下一可执行价格、费用、滑点和停牌；即使平台不自动交易，也需要防止虚假的建议收益。
7. 比较公司论点、估值区间和技术择时的增量价值：逐层消融，而不是只看最终 BUY/SELL 命中率。

## Chief 的最小运行协议

Chief 每次只接收检索器返回的证据包、确定性计算结果、已批准规则和组合约束，并返回固定结构：

```json
{
  "company_thesis": {"status": "intact", "evidence_ids": [], "disconfirming_ids": []},
  "security_thesis": {"readiness": "conditional", "range": null, "quote_as_of": null},
  "position_action": {"label": "ABSTAIN", "detail": "WAIT", "approved_rule_ids": []},
  "assumptions": [],
  "kill_criteria": [],
  "next_proof_point": null,
  "blocking_gaps": []
}
```

系统在模型输出后重新检查证据 ID、时间、行情、公式和规则权限。任何不存在的引用、越权规则或缺字段都拒绝发布。Chief 可以提出“我想检索什么”和“候选经验是什么”，不能声明新事实、删除旧证据或将候选经验变成正式规则。

## 第一阶段实现范围

先实现不可变证据、决策快照、报价时点、三层结论、`ABSTAIN`、盲评复盘和规则候选。向量检索可用现有数据库扩展或轻量索引；暂不引入可自编辑 agent memory。等账本积累至少数个季度，再决定是否需要 Mem0/Letta 类组件。LangGraph 类 checkpoint 可用于任务恢复，但其数据应与审计账本分库或至少分表，避免把运行状态误当成投资事实。

验收时选一只持仓和一只观察股做历史重放：证明同一 cutoff 能复现相同证据集与结论；注入截止日后的材料会被拦截；删除报价时间会强制 `ABSTAIN`；修改已审批快照会触发哈希告警；揭示收益前完成过程评分；未通过统计门禁的“经验”无法进入已批准规则。做到这些，平台才真正具备可学习、可追责且不过度自主的决策记忆。
