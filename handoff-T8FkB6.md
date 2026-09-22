# Cash Machine / Spec 001 会话交接

## 交接目的

- 日期：2026-09-22（Asia/Shanghai）。
- 工作区：`D:/Personal_Project/cash-machine`。
- 分支：`codex/001-investment-research-framework`。
- 用户要求在此处暂停并交给下一会话；不要把本交接视为实现或验收完成。
- 下一会话应继续 `specs/001-investment-research-framework/tasks.md`，先收口正在进行的 T054，再按依赖推进离线任务。

## 新会话必须先做

1. 读取根目录 `AGENTS.md`；它是当前项目协作规则，优先于旧会话中的同项目规则。
2. 主 agent 亲自读取当前任务、依赖、被引用的 FR/SC、决策、合同和受影响源码。
3. 读取 `docs/intent.md` 与 `.specify/memory/constitution.md`。
4. 读取当前 feature 的 `spec.md`、`plan.md`、`plan-assumptions.md`、`tasks.md`、`acceptance.md`、`data-model.md`。
5. 按当前任务读取 `contracts/cli.md`、`contracts/calculations.md`、`contracts/bot-workflow.md` 和 `quickstart.md` 中相关部分。
6. 检查 `git status --short`，保存所有既有改动；不要 reset、clean、覆盖、顺手格式化或吸收无关文件。
7. 重新检查协作 agent 状态；交接时只有 root 存活，旧 `foundation`、`memory`、`preflight` handle 已失效。
8. 开发工作必须委派给新 worker，固定 `model=gpt-5.6-sol`、`reasoning_effort=medium`。
9. 主 agent 只做任务选择、授权上下文阅读、diff/证据审计、缺口判断和验收，不亲自补代码、测试、文档或 checklist。
10. 建议使用 `$speckit-implement` 继续本地任务；恢复原生 Grok 现场核验时再使用合适的 computer-use 能力。

## 当前任务状态

- `tasks.md` 共 61 项：38 项已勾选，23 项未勾选。
- 已接受：T003–T011、T013–T015、T017–T024、T026–T033、T035、T040–T044、T050–T053。
- T012 的离线 prompts 已接受，但原生已加载版本未核实，所以仍未勾选。
- T001/T002 未完成；所有依赖原生 Grok、live source、live brokerage、Routine 或目标云部署的验收仍未完成。
- 工作树包含大量历史 planning 改动和大部分未跟踪实现；本轮没有 stage、commit 或 push。
- `.specify/extensions/git/git-config.yml` 中实现前后 Git hooks 关闭；不要自行恢复或自动提交。

## 证据等级

- 已接受的实现证据主要是 Windows 本地、离线、合成数据、fake SDK 或 MockTransport。
- 它们不证明金融语义正确、真实数据覆盖、真实券商完整性、原生 Grok 行为、云端安装或最终 Gate。
- 详细任务证据以 `tasks.md` 的 audit evidence 和 `tmp/*-report.md` 为准，避免在新文档中重复整套计划。
- 关键报告：`tmp/source-router-report.md`、`tmp/valuation-engine-report.md`、`tmp/decision-records-report.md`、`tmp/portfolio-integration-report.md`。
- 记忆报告：`tmp/memory-retrieval-report.md`、`tmp/memory-methods-report.md`。
- 因子基础报告：`tmp/expression-report.md`、`tmp/operators-report.md`、`tmp/time-alignment-report.md`、`tmp/trials-report.md`。
- 供应链 fixture 报告：`tmp/supply-chain-fixtures-report.md`。

## 当前最优先：T054 尚未验收

- T054 checkbox 仍为空，尚无最终测试报告或 root 接受结论。
- `tests/integration/test_memory_roundtrip.py` 已包含版本冲突、历史版本、真实 packet 内容和归档来源篡改场景。
- 最后一个测试是 tampered Decision source 检查；此前无意义的 keyword/no-action pytest 已删除。
- `src/cash_research/memory.py` 的通用归档 source 分支已核对 manifest 的 `record_id`、`record_type`、`canonical_ref` 和文件 hash。
- 对缺少旧 manifest hash 的记录，当前实现加入 unknown/limitation，而不是静默信任 `archived_at`。
- `bot-kit/skills/research-entry/SKILL.md` 已加入 priority、expiry、现行指令优先和 `no_change` 路径。
- 上述都是未验收 WIP；下一会话应先审 actual diff，再跑最窄的 T054 owning test。
- 测试 fixture 已覆盖 periodic 与 long-running；deep-analysis 使用手工等价案例。
- 接受前应核对 deep-analysis 与第三个 fixture 的要求是否等价，不能只凭段落或关键词存在判通过。
- 若审计发现问题，发回负责 worker 修复并重新验证；主 agent 不直接 patch。
- 通过后由 worker 更新 T054 checkbox 与证据文字，主 agent 再审。

## 可并行推进的供应链方法

- T036 与 T037 在 T035 后相互独立，可由两个不重叠 ownership 的 worker 并行。
- T036 现状未实现：`bot-kit/tasks/supply-chain.md` 仍是 v0.3，并保留 “up to three candidates” 固定上限。
- `bot-kit/skills/supply-chain-research/SKILL.md` 不存在。
- `tmp/supply-chain-method-report.md` 不存在。
- T036 ownership 还涉及 `bot-kit/README.md` 和 packager allowlist；先按 task 的精确引用范围分配。
- T037 只改 `bot-kit/tasks/company-thesis.md` 及其任务授权范围，不复制 valuation 公式。
- T038 修改 `bot-kit/skills/research-entry/SKILL.md`，必须在 T036/T037 完成且 T054 释放该文件后串行集成。
- T035 已接受的四类 fixture 是 theme-only、rejected、conflict、no opportunity；静态证据不是语义或原生验收。
- no-opportunity Decision 的实际 label 是 `no_opportunity`；来源使用 hash/ref，不把全部 source 复制进归档。

## 因子链：T045 仍需先审设计

- `src/cash_research/calculations/factor.py` 与 `validation.py` 尚不存在。
- 之前只有 T045 提案，没有 root 批准，也没有实现授权结论；新会话先审提案与 T040–T044 实际接口。
- 提议入口是 `execute_factor_experiment(root, experiment_id, *, qualification, protocol, event_tables, replay_of_by_parameter)`；名称和形状都不是既定事实。
- 协议提议包含 primary metric、minimum N、train-only selection、tolerance、block length、resamples、seed 和 cost meaning。
- 数据资格需冻结 source hashes、evidence、sessions、availability；表达式计算应保留 full history，再批量生成集合。
- 必须做到 chronological split、target/label purge、train-only fit/parameter selection、validation confirmation。
- 在计算任何 holdout metric 前记录 holdout exposure；默认只在 holdout 评估选中 arm。
- 若预声明 all-arms holdout，只能作为明确 exploratory 报告，不能隐藏多重尝试。
- protocol、qualification、policy 选择必须在 precompute 前冻结并 hash；不要用隐藏可变参数破坏完整请求。
- baseline accuracy/distribution 的单位必须一致；样本不足不能伪装为 stable `no_increment`。
- T040 的 30-minute/day fixture 只证明手算，不因数学可算就自动成为 PIT-qualified 数据。
- “row partition resource refusal” 不得未经审查变成固定研究上限；需与 P05 可配置、无损 batching 对齐。
- 不要凭空添加最低样本数或其他产品要求；若实现需要默认值，必须来自批准合同或声明充分的研究理由。

## T044 与 T045 的交界风险

- 当前 `start_trial` 要求原 trial 已 terminal，导致基础设施中断后的 exact retry 可能产生额外 candidate count。
- 曾提出允许严格匹配的 nonterminal `infrastructure_retry`，但尚未实现或批准。
- 若处理此缺口，必须保持 request/data/summary hash 全匹配、lineage 无环，并保留 holdout exposure marker。
- 现有 exposure 在 eval 前写入，使用 per-instrument OS lock。
- overlap 以实际 time/security/compatible exchange + target operation/field 判断；不依赖 request/trial group/dataset hash。
- frozen experiment 比较 canonical request、dataset 和 summary hashes，并记录 failed、abandoned、exact replay 次数。

## 已接受的时间对齐边界

- `EventRevisionTable` 和 `QualificationEvidence` 分开表达 observed time、aware/available time 与知识窗口。
- 完整历史必须显式声明，不能由日期推断。
- `BarCoverage` 用正 interval/full sessions 生成准确 start/end grid；`1d` 明确使用 trading day。
- `event_age` 从事件后第一个 bar boundary 开始数完整 bar，不把午休或隔夜算成 bar；clipped prefix 必须拒绝。
- date period 使用已声明 market timezone，不能伪造 UTC midnight。
- action conversion 需要独立、完整的 corporate-action coverage；unknown 与 explicit empty 必须区分。
- T045 resolve 需要暴露 event/action coverage 以及每个实际 action ref。
- raw 默认不变，adjustment 不可重复应用；输出需保留 observed/effective/available 与 event-age query time。
- 审 T045 时必须读当前模块，不用本段替代源码和合同审计。

## 原生与 live 阻塞

- 详情见 `tmp/preflight-report.md`；T001/T002 保持未勾选。
- computer-use 两次（含 reset 后重试）都在 browser/surface inventory 前失败。
- 错误：`node_repl kernel exited unexpectedly`；诊断为 `windows sandbox failed: helper_unknown_error: apply deny-read ACLs`。
- 因此没有核实实际 Grok Bot/Routine 映射、cloud Python、私有路径、Skills、terminal 或 live source 请求。
- 未打开、打印或隐式加载 `sec-analysis.env`；没有执行真实金融或账户请求。
- 数据或访问阻塞只阻塞相关 live case；继续独立离线工作，但不得降低最终验收标准。

## 环境与依赖事实

- 稳定 PowerShell：`C:/Users/Public/PowerShell/7/pwsh.exe`；不要使用 WindowsApps alias。
- Coreutils 在 `C:/Program Files/coreutils/coreutils.exe`。
- `uv` trampoline 在 sandbox 中曾报 OS error 5；已有 `.venv/Scripts/python.exe` 可在批准的 escalated exec 中运行。
- 不要新建 venv 或 cache。
- base lock 为 25 packages；可选 AKShare 1.18.97 + Longbridge 4.5.0 后共 48 packages。
- Longbridge SDK 5.1 没有 CPython 3.12 Windows wheel；4.5.0 OAuth stub 只用 fake SDK 验证。
- 当前 code graph 的 `index_status`/`check_index_coverage` 返回 Transport closed。
- 最后已知 graph generation 是 2026-09-21T06:17:20Z，状态 `metadata_changed`；当前断言用直接源码读取兜底。

## CLI、ID 与尚缺能力

- CLI 已有 `data fetch`（四个公共数据源＋两家只读券商，共六个既有集成）、`data ingest`、`compute valuation`、`check artifact`、`memory recall/apply`。
- `check artifact` 默认只读，只有 `--archive` 才固化。
- canonical IDs：`rec_`、`evi_`、`calc_`、`snap_`、`mem_`，返回后必须可解析。
- `compute factor` 尚未实现。
- models 对 time、unit、unknown 使用显式字段；不要以默认值掩盖未知。

## 文档同步缺口

- `specs/001-investment-research-framework/acceptance.md` 缺 T033、T035、T044 的表格行。
- 这些任务已在 `tasks.md` 勾选并有 audit evidence；补表时引用现有任务报告，不重开已接受行为。
- T043 行存在。
- T030 行仍写 “CLI T033 pending”，是历史上下文，现已过时；同步时只修证据映射，不改验收标准。
- 该同步缺口不影响当前 T054 代码审计，但应在后续 acceptance 维护中补齐。

## 后续依赖顺序

1. 审计并完成 T054；确认测试、证据和 checkbox 一致。
2. 并行完成 T036 与 T037；随后串行 T038。
3. 审查 T045 方案，解决 T044 retry/holdout 交界，再实现 T045。
4. 依次推进 T046、T047、T048；`cli.py` 必须由单一 owner 串行集成。
5. T034、T039、T049、T055–T059 只在各自原生/live 依赖恢复后验收。
6. T060 的离线 guides/runner 可提前准备，但整项依赖 T059，不能提前勾选。
7. T061 只有 T057–T060 与所有 SC 通过后才能勾选并宣布 feature 完成。

## T060 与发布注意

- `scripts/run_fixtures.py` 目前主要渲染 request JSON；最终要执行完整 fixture 调用并使用真实返回 ID 回填引用。
- T032 report/template 链仍需 copy/render fixture、reports/support files 和实际 `memory_packet_as_of` token。
- 六份模板只有 T048 后才完整。
- 数值比较必须使用实际输出对 expected，不能伪造 ID。
- `calculation-limits.example.json` 尚未由 T048 打包/接线。
- `tmp/releases` 下 T015 zip 已过期，不可部署。

## 不得越过的产品边界

- 目标是既有 native Grok Bot 的 24/7、Routine、多 Agent、手机/PC、Skill/terminal 能力。
- 不建设第二套 agent 平台、scheduler、recovery service、notification system 或 trading engine。
- 六个既有集成固定为 Finnhub、Tiingo、FMP stable、AKShare、IBKR Flex、Longbridge OAuth。
- Web Search、公司 IR、交易所/监管披露和用户材料是证据通道，不是新增供应商。
- 券商只读；绝不提交、修改或取消订单，读取失败也不能解释为空仓。
- `archive/` 只读参考，不执行、不导入、不演进为 active application。
- 私有持仓、凭证、Bot mapping 和 runtime data 不进入 Git 或共享报告。
- 不自动 commit/push；用户没有授权发布。

## 交接结束状态

- 本文只记录可继续工作的边界和当前 WIP，没有运行测试或更改实现。
- 新会话应从 T054 actual diff + focused test 开始，而不是从本交接推断其已完成。
- 所有最终结论仍以当前源码、`tasks.md`、`acceptance.md` 和对应验证输出为准。
