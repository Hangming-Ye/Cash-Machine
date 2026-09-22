# Phase 0 Research: Spec001 方案收敛

2026-09-20。状态：用户已批准本轮设计决策，见 [审批记录](plan-assumptions.md)。所有架构选项已选择一条可实施路径；账户字段／权限和 Grok 行为仍按现场验证处理，不表示已实测。

## R-01 数据基线

**Decision**：严格沿用当前 Finnhub、Tiingo、FMP stable、AKShare、IBKR Flex、长桥只读；遗漏登记在 [data-sources.md](data-sources.md)。现有源失败时用已接入的适用路径或 Bot 搜索／原披露补证，不采购或引入新供应商。

**Rationale**：用户最新明确指令。handoff 提供现有配置声明，研究 13 提供实现与映射限制；用户已确认券商能力与凭证，无需再次把接入当可选未来项。

**Alternatives considered**：重新评估商业行情／研报源——本轮不做；将全部来源调查未完成作为开工阻塞——不采用；以搜索替代历史数据集——不成立。

**Evidence**：[handoff](../../HANDOFF_FOR_SENIOR_PLANNER_20260920.md)、[代码审阅](../../research/13-current-data-implementation.md)。本轮不读取秘密、不 live 调用。G-01—G-08 可影响最终完整案例通过，不能靠降级报告抹掉。

## R-02 Grok Bot 原生入口

**Decision**：Description 定义岗位及方法入口，Skill 定义可组合研究步骤，现有 Routine 触发，原生消息和共享文件交接。开发一个按需 CLI 辅助计算与资料，不创建 Bot 运行控制器。

**Rationale**：公开产品能力足以提供上述入口；无法证明内部 prompt／记忆可替换或每次模型调用可被 hook。岗位与共同指令以 bot-kit/prompts/ 的现有文件逐一迁移并核对实际加载，岗位和上下文必须显式交付，不能依赖父会话。

**Alternatives considered**：自建 Agent runtime、Bot API 轮询、原生模型强制选型——不采用。固定少量工作流白名单——会收窄开放研究要求，不采用。

**Evidence**：[产品及案例研究](../../research/15-grok-memory-integration.md)、[官方 Skill／Routine](https://docs.x.ai/grok-bot/skills-routines-and-automations)、[共享电脑](https://docs.x.ai/grok-bot/computer-and-apps)。

## R-03 程序与存储

**Decision**：新建 Python 3.12 包／CLI，uv 锁依赖，使用 pandas／NumPy／SciPy、Pydantic、httpx 和既有源的 SDK。JSON／CSV／Markdown 存共享私有目录；不要 Web 服务、队列、向量库或 SQL 调度库。P-01—P-02 已批准。

**Rationale**：数值与适配器可复查，文件与 Bot 原生交接一致，复杂且确定性的步骤从模型移到小程序；旧库能参考但无需兼容。

**Alternatives considered**：直接把旧 sec-analysis 当完整系统——其仅覆盖部分取数；另建前后端／微服务——对当前入口无必要；整体安装金融 Agent 框架——引入第二套运行与模型假设。

**Validation**：先核对云机 Python／网络／安装权限，用锁文件复建；不能以手装依赖永久存在为假设。固定样例测试与现场取数分开。

## R-04 供应链与价格判断

**Decision**：复用 Serenity 的研究顺序及证据阶梯，结合公司业务暴露、利润兑现、估值和反证；模型提出假设，程序承担 DCF／倍数／EV 桥／分部或资产法的计算。

**Rationale**：角色名称和信息汇总不足以输出可参考判断；方法必须落实到具体问题与证据，而算术、单位与敏感性由程序保证可复查。

**Alternatives considered**：固定评分排行榜、多个投资人格投票、平均目标价、只用技术支撑位作为公允价值——均不采用。早期线索不强求成熟财务模型，可保留有依据的条件。

**Evidence**：[Serenity 方法审阅](../../research/02-supply-chain-skills.md)、[prompt 审计](../../research/10-financial-prompt-source-audit.md)、[场景方法](../../research/11-financial-scenario-playbooks.md)。旧文件中的候选数／固定阶段数不是本计划要求。

## R-05 开放因子组合

**Decision**：用命名操作构成小型结构化表达；公式／参数可在任务中组合并冻结后执行。注册的是输入、操作和验证规则，不是每条新公式。粒度由实验参数指定，日频先做验证样例；非日频依赖现有源或可追溯材料的实际覆盖，边界见 [calculations.md](contracts/calculations.md)，P-05 已批准。

**Rationale**：解决旧任务卡把新公式退回开发的冲突，同时避免弱模型自由写代码。pandas 的 rolling／EWM 等操作可作为确定性基础；PIT 用 backward as-of 语义，但必须有真实可得时点与版本材料。

**Alternatives considered**：固定 12 因子／只能选择已注册公式——不足；任意代码沙盒或 RD-Agent coder loop——增加运行风险与维护；自由自动参数搜索——增加选择偏差。复杂新原语仍需工程扩展，不能承诺当前能力覆盖所有数学方法。

**Evidence**：[单票研究](../../research/03-factor-research.md)、[pandas Window](https://pandas.pydata.org/docs/reference/window.html)、[pandas merge_asof](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html)、[SciPy stats](https://docs.scipy.org/doc/scipy/reference/stats.html)。本轮子 agent 补充核查了操作组合、时点及试验记账方案；未安装或执行引擎。

**Validation**：截断未来不改变过去、固定输入复算、事件时间边界、复权、样本隔离、试验计数；一个首次提出的合法组合必须无需开发改码即可完成实验。

## R-06 有效记忆

**Decision**：先用主题摘要和有条件经验文件，按当前问题与时点读取并实际交给专员；历史模式按 known_at 选择当时版本，review 模式将原判断输入和后续事实分区；提炼由现有 Bot 按 Skill 执行，小程序做字段／引用／预算检查。定时重增量、长期重假设演变、重分析重依据与条件。P-07 已批准。

**Rationale**：Mem0 不自动把返回记忆注入 Grok；LangMem 的库依赖与 Letta 的原生上下文机制不能直接当 Bot 插件。初版可提取其合并压缩方法，无须先接另一个模型服务。

**Alternatives considered**：只用原生隐式记忆／只存日志——无法检验完整闭环；Mem0 Platform——保留为词项／主题检索不足的候选；Letta 迁移、图记忆库、独立后台反思系统——本轮不引入。

**Evidence**：[组件及源码](../../research/14-memory-consolidation.md)、[Grok 接入与金融研究样例](../../research/15-grok-memory-integration.md)。

**Validation**：新会话、Routine、专员交接三入口；重复／无关／过时／反证／跨措辞材料；记录实际交付记忆及研究如何使用，不能只看 self-report。

## R-07 写入与恢复复杂度

**Decision**：原始判断／执行／复盘通过 check artifact 的显式 --archive 追加固化，默认检查不写入；主题／经验由负责人更新，单次写入检查 expected_version 并原子替换，保留旧版。失败说明原因并简单重跑。P-08 已批准。

**Rationale**：并发覆盖会破坏长期研究，但不需要为此建任务状态机。文件级串行更新解决具体冲突；无需跨文件事务、消息队列或调度补偿。

**Alternatives considered**：最后写入者覆盖——丢反证与历史；完全只追加——无法提供精简当前摘要；分布式状态／租约系统——不必要。

## R-08 交付与验收

**Decision**：原生聊天的统一摘要与产物链接，按 spec 核心案例及异常检查。实施分片见 plan，记忆从早期研究就接入；P-09 已批准。

**Rationale**：尽早验证受限产品的真实入口，避免先建大量程序最后才发现 Bot 不执行方法；三类最终完整交付仍须完成。

**Alternatives considered**：手机专用 UI、通知系统、7 天运行 SLA、先只做某一市场或永远把其他能力留二期——不采用。

## 不再悬置的事项与验证边界

设计路径已决定：数据基线按用户锁定，因子采用组合运算，记忆以文件与原生方法优先；未知不再用供应商罗列或“以后选组件”掩盖。实际数据覆盖、依赖环境与 Bot 执行效果列入 quickstart 的具体检查；未实测的项目保持未验证。

用户已批准本轮 P-01—P-09，并要求生成任务。审批不是另一次用户需求访谈；若不接受某项，修订相应设计及契约即可。原 [plan-readiness.md](plan-readiness.md) 中的两项 Phase 0 问题已分别由 R-01、R-05 收敛，旧文件作为检查记录保留。
