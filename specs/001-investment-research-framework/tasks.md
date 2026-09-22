# Tasks: 持续投研与决策支持框架

**Input**: [spec.md](spec.md)、[plan.md](plan.md)、[research.md](research.md)、[data-model.md](data-model.md)、[contracts/cli.md](contracts/cli.md)、[contracts/calculations.md](contracts/calculations.md)、[contracts/bot-workflow.md](contracts/bot-workflow.md)、[quickstart.md](quickstart.md)。

**Approval**: 用户已批准 plan，要求转 tasks 并列出新增决策。实施已按用户授权开始；当前完成状态以任务复选框和 [acceptance.md](acceptance.md) 的分级证据为准。本轮新增拆分决策见 [task-decisions.md](task-decisions.md)。

**Tests**: spec 的独立测试与 SC-001—008、plan 的数值／契约／原生行为验证明确要求测试。以下只为这些风险生成测试任务，不给纯文档改写添加形式化单元测试。新增功能测试先于对应实现；产品测试仅在对应任务及环境条件满足时运行并分级记录。

## Format and Paths

- 所有任务为 `- [ ] Txxx [P?] [USn?] 描述`。`[P]` 仅表示本行列明前置任务完成后，能与同批不同文件任务并行。
- 普通路径相对仓库根 `D:/Personal_Project/cash-machine`。离线与本机证据写在仓库内 gitignore 的 `data/preflight/` 与 `data/validation/`。云端 `/workspace/cash-machine/` 与 `/workspace/cash-machine-test/` 仅在该文件系统真实存在时作为部署 root。无法打开云端路径不使任务保持未完成，也不算 live 检查通过。账户、凭证与 Bot 映射仍不入 Git。
- 本次开发只在本机 Cursor / dev 验证。本地测试、文件审核或无父会话子 agent 按独立简报执行通过，即勾选。不要求 live 接口、云端部署、原生 Grok、手机／PC 或定时 Routine。证据等级写 local Cursor 或 subagent specialist，不得改称为 live 或原生通过。
- 任务说明含产物与完成判据。路径尚不存在的由实施者创建；不得将其误认为当前已实现。
- 同一 `cli.py`、`models.py`、`memory.py`、`artifacts.py` 的改动由当阶段负责人顺序集成，不能因跨故事并行而同时覆盖。
- 所有用户故事均为 P1。按已批准交付顺序排列 US4→US5→US2→US1→US3→US6，编号保持 spec 身份。US6 的最小读写在基础阶段实现，各故事从第一轮就使用，不等末期才有记忆。

## Phase 1: Setup — 环境与覆盖前置检查

目标：核对现有环境和数据；不重新初始化 Git，不动 archive，不扩供应商。

- [X] T001 清点已有 Grok Bot／Routine、Skill／终端入口、云端 Python、项目路径及职责，生成 `data/preflight/t001-native/config/bot-mapping.json` 和 `data/preflight/t001-native/data/preflight/environment.md`；记录可见信息与不可见项，不创建新生产 Bot、调度器或回调。
- [X] T002 使用当前云端已有只读通道探测六类来源、港股历史、复权／PIT、研报／社交、自选声明冲突，记录 `data/preflight/t002-local/source-coverage.json`，更新 `specs/001-investment-research-framework/data-sources.md` 的脱敏事实；列明 G-01—G-08 哪些影响完整案例，可追溯导出／公开序列导入是否可行，不能伪称 live 成功（依赖 T001）。
- [X] T003 建立新包 `src/cash_research/__init__.py`、`pyproject.toml`、`uv.lock` 和 `config/settings.example.json`，按已批准 Python／依赖组合固定兼容版本及入口；`uv sync --locked` 可复建，示例无秘密，不导入归档作为活动应用；参考 T001 环境记录，云端不可访问时仍按已批准 Python 3.12 建立离线工程，现场兼容验证留在 T016。
- [X] T004 [P] 在 `fixtures/scenarios/manifest.json`、`fixtures/README.md` 和 `tests/conftest.py` 建立三市场×三类研究、八类异常及记忆样例映射；在 `scripts/run_fixtures.py` 建立仅供验证使用的 runner 骨架，分步调用 CLI、填回返回 ID／版本、保留逐步结果；在 `specs/001-investment-research-framework/acceptance.md` 创建未执行／受阻也可更新的验收映射骨架，虚构资料标 synthetic（依赖 T003）。

**Checkpoint**：T001/T002 的完成表示已取得可验证记录，不要求所有源无缺口。账户或环境不可访问时，相应现场任务保持未完成；独立本地任务可继续。数据缺口只阻塞依赖该数据的完整案例，不冻结其他模块，也不允许最终验收假通过。

**T001 audit evidence**：2026-09-22 检查原生 Grok UI 0.57.1，可见既有云端／源码路径；私有 `data/preflight/t001-native/config/bot-mapping.json` 与 `data/preflight/t001-native/data/preflight/environment.md` 保存替换前 Bot/Routine 快照及环境清点。软件开发工程师 Bot 自报 Debian 13、`/usr/bin/python3` 3.13.5、`/usr/local/bin/uv` 0.12.15、`/home/box/agent-data/managed-skills/skills` 下 44 个托管 Skill 文件且 workflows 为空，未取得独立原始命令日志。新 Bot 实际部署访问、Skill 调用和完整 Routine 登记留 T016 验证。Bot 违反只读要求，以 `uv run` 探测在旧源码根 `/workspace/sec-analysis-src/sec-analysis` 创建 `.venv` 并获取 build dependencies；完整改动范围及完成程度未知，未授权或执行清理。未创建生产 Bot、调度器或回调。

**T002 audit evidence**：2026-09-22 以显式受保护配置对六个既有来源执行本地只读 live 探测，私有 `data/preflight/t002-local/source-coverage.json` 记录 `recorded_with_gaps`。Finnhub、Tiingo、FMP stable、AKShare、IBKR Flex 与长桥 OAuth 均取得成功、部分成功或明确错误证据；长桥直连 SDK 账户与持仓读取成功，但项目适配器仍缺受保护账户引用且自选未验证。港股 00700 原始／qfq 各导出 260 行，可追溯导入但不证明 PIT／公司行动完整；G-01—G-08 均保留影响说明。未新增供应商、未调用订单写接口、未记录凭证值。

**T003 audit evidence**：Windows 离线工程执行 `uv sync --locked`，同步 25 packages 且退出码 0；`cash_research` 与计划中的核心依赖导入成功。该证据不替代 T016 的云端兼容和原生入口验证。

**T004 audit evidence**：主 agent 审核并接受 validation-only skeleton；manifest 为 9 core／8 exception／3 memory／6 workflow 且 synthetic，conftest loader 输出 `9 8 3`，`py_compile`、`--help` 和 `git diff --check` 通过；缺模板运行退出 2 并记录 `not_run`，artifact ID／版本捕获及路径逃逸拒绝 probe 通过。完整链与数值 expected 对照仍由后续模板任务和 T060 完成。

## Phase 2: Foundational — 共享的最小能力

目标：只建立各故事共用的契约、记录和最小记忆能力。故事实现从 T005—T011 完成后开始；现场访问问题不阻塞离线开发。

- [X] T005 在 `src/cash_research/config.py` 和 `tests/unit/test_config.py` 实现 root／配置／显式 env-file 读取及操作白名单；默认不读取本地 `sec-analysis.env`，拒绝请求中携带秘密和订单操作，日志不回显凭证（依赖 T003）。
- [X] T006 在 `src/cash_research/models.py` 与 `tests/contracts/test_models.py` 实现 data-model 的共享实体与调用结果契约；未知时间／数值为 null、有原因，证券／单位／币种明确，complete／limited／failed 与投资判断分开（依赖 T005）。
- [X] T007 在 `src/cash_research/artifacts.py` 和 `tests/unit/test_artifacts.py` 实现安全相对路径、唯一 ID、不可覆盖的原始记录、出处定位及单产物完整写入，并提供 Decision／WorkRecord／Review 的基础校验归档函数以供首个 Bot 样例使用；路径逃逸、旧判断覆盖与秘密字段进入可共享产物的样例被拒绝（依赖 T006）。
- [X] T008 [P] 在 `tests/contracts/test_cli.py` 定义已批准七组命令、JSON 信封、退出码与 partial／empty／error 区别的契约测试；不得以空持仓代替读取失败（依赖 T006、T007）。
- [X] T009 在 `src/cash_research/cli.py` 建立按需入口、请求加载与结果序列化，接入 T007 的 check artifact 默认只检查及显式 --archive 归档；其它处理器按后续任务挂接，未实现的操作明确失败，不伪返回成功；入口和错误契约测试通过（依赖 T008）。
- [X] T010 在 `src/cash_research/memory.py` 与 `tests/unit/test_memory_storage.py` 实现主题／经验的基础索引与读取、版本检查、保留旧版、单次写入串行校验／原子替换；区分无历史与读取失败，冲突不覆盖已有结果（依赖 T007）。
- [X] T011 在 `bot-kit/skills/research-memory/SKILL.md` 写明任务前读取、研究后提炼合并及回写的方法，并为主题／经验版本记录不可回填的 known_at，加入 context_mode 的版本筛选与复盘分区；将基础 `memory recall/apply` 接入 `src/cash_research/cli.py`；用 `fixtures/requests/memory-recall.json`、`fixtures/requests/memory-update.json` 完成一次真实文件读写往返（依赖 T009、T010）。

**Checkpoint**：有可执行的小工具与最低有效记忆循环；尚不能声称金融研究能力或复杂记忆效果已通过。

**T005 audit evidence**：Windows 离线执行聚焦配置测试，17 passed；覆盖 root／显式 env-file、操作白名单、订单拒绝及凭证键处理。测试未加载 live 凭证，也不证明云端配置可用。

**T006 audit evidence**：主 agent 审核实际模型与测试后接受；Windows 离线合并检查 30 passed，并通过 `uv lock --check` 与 `compileall`。证据仅覆盖共享模型／契约，不证明 live 数据或原生 Grok 行为。

**T007 audit evidence**：主 agent 审核实际 artifacts 实现与测试后接受；Windows 离线聚焦检查 22 passed 且 `git diff --check` 通过，包含模型内悬空引用和校验后草稿变化拒绝。证据仅覆盖本地产物校验／不可变归档。

**T008/T009 audit evidence**：主 agent 阅读修订后的 CLI 源码、契约测试和报告后接受，最终 `git diff --check` 通过；CLI 聚焦测试 33 passed，最终 T005—T009 合并回归 85 passed。`uv lock --check`、`uv sync --locked`、`compileall` 及已安装 `cash-research --help` 均通过。证据为 Windows 离线契约／入口，不是 live source 或原生 Grok 证据。

**T010 audit evidence**：主 agent 阅读最终 memory storage 实现与测试后接受；聚焦检查 13 passed（含真实进程竞争），相关合并回归 48 passed。证据仅覆盖 Windows 离线文件记忆存储。

**T011 audit evidence**：主 agent 完成代码、Skill、请求模板及真实文件读写往返审计并接受；Windows 离线完整回归 110 passed。证据覆盖基础 memory recall/apply 和方法入口，不证明原生 Grok 记忆效果。

## Phase 3: US4 — 在既有 Bot 环境中委托研究 (P1)

**Goal**：验证原生入口与充分任务上下文，排除后期才发现无法调用的风险。

**Independent Test**：同一合成研究从新会话、隔离 Test run、原生专员交接执行；只读测试资料，能简单重跑，手机 PC 看同一结果。完整真实研究的再次验证在 T057—T061。

- [X] T012 [US4] 逐一迁移 `bot-kit/prompts/common.md`、`bot-kit/prompts/chief.md`、`bot-kit/prompts/research.md`、`bot-kit/prompts/market.md`、`bot-kit/prompts/quant.md`、`bot-kit/prompts/reviewer.md`，并更新 `bot-kit/README.md` 的实际加载清单；改写或停用旧固定流程、逐公式退开发、补证数量上限及调度命令，本机核对六个 prompt 文件与 README 加载清单版本即可，不要求 Bot 运行时加载；不另建 roles/ 或第二份 common（依赖 T011；现场映射依赖 T001）。
- [X] T013 [P] [US4] 在 `bot-kit/skills/research-entry/SKILL.md` 和 `bot-kit/templates/task-brief.md` 实现目标／范围→方法组合→充分上下文→产物交接的方法；移除固定流程／候选数白名单，不创建任务节点状态库（依赖 T012）。
- [X] T014 [P] [US4] 在 `bot-kit/templates/report.md` 与 `bot-kit/tasks/review.md` 定义统一结论、依据、反证、期限、缺口和下一步；手机 PC 不分格式，复核回查来源不以投票代替证据（依赖 T012）。
- [X] T015 [US4] 在 `scripts/install.ps1`、`docs/deployment.md` 明确开发机打包、云机 uv 安装和版本回滚的手工路径；代码／锁文件可复建，秘密和运行数据不打包，步骤只操作项目目录，不加自愈进程（依赖 T013、T014）。
- [X] T016 [US4] 在本机 Cursor 用新子 agent 验证独立简报交接、两个任务分别归属，以及缺输入失败后的重跑；记录 `data/validation/us4-entry.md`。不部署云端，不建 Routine，不要求手机或 PC（依赖 T015、T012）。
Evidence: local Cursor / subagent specialist in `data/validation/us4-entry.md` (specialists A/B ownership, fail then retry); not cloud, not Routine, not phone/PC, not native Grok.

**T012 audit evidence**：2026-09-22 本机核对六个 prompt 均为 v1.0（common、chief、research、market、quant、reviewer），`bot-kit/README.md` 加载清单与文件对应，未另建 roles/ 或第二份 common。prompt 目录无固定候选上限、逐公式退开发和调度命令。按 TD-08，不要求 Bot 运行时加载核对。

**T013/T014 audit evidence**：主 agent 审核实际 Skill／模板／复核文档和静态路径，并完成语义 diff 检查后接受离线实现。证据不替代 T016 的原生入口、手机／PC 与专员交接验证。

**T015 audit evidence**：主 agent 审核安装脚本、部署文档及 fail-fast 修复后接受；Windows 离线 packaging 检查 4 passed。证据不替代 T016 的云端安装、回滚和原生入口验证。

## Phase 4: US5 — 数据受限时主动补证 (P1)

**Goal**：将现有来源转成可信材料，缺口不造成任务机械放弃。

**Independent Test**：阻断首选源，提供可追溯的替代公开材料；保留来源与时点并继续研究，无法取得的历史数据明确受限。

- [X] T017 [US5] 在 `tests/contracts/test_sources.py`、`fixtures/sources/expected.json` 定义 quote／bars／news／profile／statements、文本／序列导入、部分成功及七类数据错误的样例；验证未知时间、修订、复权和原始源字段不被默认值掩盖（依赖 T011、T004）。
- [X] T018 [P] [US5] 在 `src/cash_research/sources/finnhub.py` 与 `tests/unit/test_finnhub.py` 接现有 US/HK 报价和新闻，保留时点／限额／权限与实际来源，不自动增加 candle／目标价／研报端点（依赖 T017）。
- [X] T019 [P] [US5] 在 `src/cash_research/sources/tiingo.py` 与 `tests/unit/test_tiingo.py` 接现有 US 历史日线，保留原始／调整字段与可得公司行动，禁止 raw 价格和调整成交量静默混用；不足登记 G-02（依赖 T017）。
- [X] T020 [P] [US5] 在 `src/cash_research/sources/fmp.py` 与 `tests/unit/test_fmp.py` 接 stable 公司及三表，保留实际返回的披露／修订时间和原文定位；无历史版本不得声称 PIT 已满足（依赖 T017）。
- [X] T021 [P] [US5] 在 `src/cash_research/sources/akshare_source.py` 与 `tests/unit/test_akshare.py` 接当前 CN 行情／新闻／财务入口，保留实际底层源、时区和复权口径，区分无新增与全部失败（依赖 T017）。
- [X] T022 [P] [US5] 在 `src/cash_research/sources/ingest.py` 与 `tests/unit/test_ingest.py` 实现公开文档／观点与完整数值文件的导入；保留出处、可访问范围及时间，校验序列覆盖，不将片段拼成伪历史；创建 `fixtures/requests/evidence-ingest.json`（依赖 T017）。
- [X] T023 [P] [US5] 在 `bot-kit/skills/source-followup/SKILL.md` 与 `bot-kit/tasks/event-impact.md` 编写现有源→网页／原披露补证、研报／社交取原文、冲突处理和缺口回写方法；无全文不称已审阅，领域内合理问题继续补证（依赖 T017）。
- [X] T024 [US5] 在 `src/cash_research/sources/router.py` 和 `src/cash_research/cli.py` 接入 data fetch/ingest，写 SourceResult／Evidence／DataGap；完成 `tests/integration/test_source_fallback.py` 的数据失败与公开文件补证样例（依赖 T018—T023）。
- [X] T025 [US5] 在本机用现有测试验证 Finnhub、Tiingo、FMP、AKShare 四个适配器和一次公开材料导入补证，记录 `data/validation/us5-sources.md`；G-01—G-08 沿用 T002 缺口说明。不要求 live 探测或原生网页（依赖 T024、T002）。
Evidence: local Cursor pytest in `data/validation/us5-sources.md` (133 passed); not live APIs, not native web.

**T017 audit evidence**：主 agent 审核共同来源契约与 synthetic fixtures 后接受；聚焦检查 12 passed，来源＋共享模型相关回归 25 passed。证据不表示任何 live source 已访问。

**T018 audit evidence**：主 agent 审核 Finnhub 适配器、MockTransport 测试及边界后接受；聚焦检查 30 passed，T017＋Finnhub 合并回归 42 passed。证据不表示 live Finnhub 权限、数据持久化或 CLI 集成已验证。

**T019 audit evidence**：主 agent 审核 Tiingo 适配器、MockTransport 测试及原始／调整字段边界后接受；聚焦检查 32 passed，T017＋Tiingo 合并回归 44 passed。证据不表示 live Tiingo 权限、数据持久化或 CLI 集成已验证。

**T020 audit evidence**：主 agent 审核 FMP stable 适配器、MockTransport 测试及时间／PIT／剔除行／币种边界后接受；聚焦检查 16 passed，T017＋FMP 回归 28 passed，共享模型＋T017＋FMP 回归 42 passed。证据不表示 live FMP 权限、持久化或 CLI 集成已验证；日期粗粒度筛选也不证明精确可得时点。

**T021 audit evidence**：主 agent 审核 AKShare 适配器、测试及修复后接受；聚焦检查 27 passed，T017＋AKShare 回归 39 passed，Finnhub＋Tiingo＋AKShare＋T017 回归 101 passed。证据仅为离线适配器测试，不表示 live AKShare 或 CLI 集成已验证。

**T022 audit evidence**：主 agent 审核导入实现、请求 fixture 与测试后接受；聚焦检查 24 passed，T017＋共享模型＋导入回归 50 passed。文本及 CSV／JSON 数值序列按契约验证；PDF 等不透明文件仅归档，不证明语义或 PIT，且尚未接 CLI／持久化路由。

**T023 audit evidence**：主 agent 审核来源补证 Skill、事件方法、活动清单与打包 allowlist 后接受；packaging 聚焦检查 4 passed，静态链接、旧固定上限及 diff 检查通过。证据仅覆盖离线方法与打包内容，不证明原生网页、live 来源、CLI 路由或完整研究案例。

**T024 audit evidence**：主 agent 审核来源 router／CLI、ID、持久化及记忆出处集成后接受；最终相关聚焦检查 140 passed，受影响 memory＋source 检查 44 passed。较早同修订层级曾有 public-source 159 passed／全套 396 passed，但并行后续改动使其不作为最终全套结论；无 live／native 结论。

## Phase 5: US2 — 持仓／自选综合判断 (P1)

**Goal**：尽早交付首个有用户价值的闭环，包含已有券商只读接入和可复查价位／条件。

**Independent Test**：使用一个真实持仓和对应资料完成评价；另用冻结输入独立验证估值，无需先完成供应链探索或因子挖掘。

- [X] T026 [US2] 在 `tests/contracts/test_brokers.py` 与 `fixtures/brokers/expected.json` 定义两券商只读操作、多账户／币种、T+1、部分成功、空仓／失败及禁止订单调用的契约样例（依赖 T011、T004）。
- [X] T027 [P] [US2] 在 `src/cash_research/sources/ibkr_flex.py` 与 `tests/unit/test_ibkr_flex.py` 接当前 Flex 只读通道，保留报告时间与账户覆盖，不引入 TWS／Gateway 或把 T+1 写成实时（依赖 T026）。
- [X] T028 [P] [US2] 在 `src/cash_research/sources/longbridge_readonly.py` 与 `tests/unit/test_longbridge.py` 接当前 OAuth 账户／持仓／成交，保留字段缺失与部分成功；仅按 T002 核实结果接已有自选，不开行情主源或订单写操作（核心依赖 T026；自选启用另需 T002 核验结果，不阻塞其它只读操作）。
- [X] T029 [P] [US2] 在 `tests/unit/test_valuation.py`、`fixtures/valuation/expected.json` 编写手算 DCF／倍数／EV 桥／分部与资产法样例，包含单位／币种、摊薄股本、负分母及不适用情形，创建 `fixtures/requests/valuation.json`（依赖 T026）。
- [X] T030 [US2] 在 `src/cash_research/calculations/valuation.py` 实现上述方法、情景与敏感性，保存输入引用和警告；通过 T029 的明确数值精度对照，不自动生成买卖判断（依赖 T029）。
- [X] T031 [US2] 改写 `bot-kit/tasks/valuation.md`、`bot-kit/tasks/decision-brief.md` 和 `bot-kit/skills/portfolio-research/SKILL.md`，涵盖经营／行业／走势／情绪、价格条件、反证、失效期限、资料不足及 memory 读写；无模型算术代替计算结果（依赖 T030、T013、T014、T023）。
- [X] T032 [US2] 在 `src/cash_research/artifacts.py` 与 `tests/unit/test_decision_records.py` 在 T007/T009 的基础归档入口上补齐报告正文／附件固化、previous_id 与 memory_packet_refs 关联及判断差异检查；默认检查不写入，显式 --archive 才写正式记录，失败不归档且不覆盖旧版；创建 `fixtures/requests/report-check.json`（依赖 T031）。
- [X] T033 [US2] 顺序更新 `src/cash_research/cli.py` 与 `src/cash_research/sources/router.py` 接两券商及 compute valuation，并回归已有 check artifact 的纯检查与显式 --archive；完成 `tests/integration/test_portfolio_research.py` 的合成端到端往返（依赖 T027、T028、T030、T032、T024）。
- [X] T034 [US2] 在本机运行持仓研究合成往返，记录 `data/validation/us2-portfolio.md`；读取失败不得被测试当成空仓。不读取真实账户（依赖 T033）。
Evidence: local Cursor synthetic integration in `data/validation/us2-portfolio.md` (133 passed; confirmed empty ≠ failed read); no real account read.

**Checkpoint / MVP**：US4＋US5＋US2 的首个持仓研究闭环。它是阶段交付，不等于 spec001 完成；US1、US3、US6 仍全部必须实现。

**T026 audit evidence**：主 agent 审核 broker fixtures、共享账户关联模型和契约测试修订后接受；聚焦 broker 检查 25 passed，config＋models＋brokers 相关回归 56 passed。证据仅覆盖 synthetic/read-only 合同，不证明 live 券商访问。

**T027 audit evidence**：主 agent 审核 IBKR Flex 适配器、cutoff／时区／账户覆盖修复及测试后接受；聚焦检查 31 passed，broker＋IBKR 56 passed，共享模型＋broker＋IBKR 70 passed。证据仅为 MockTransport／离线合同；真实 saved query 的时区、账户及 CSV／报告类型覆盖仍未 live 验证。

**T029 audit evidence**：主 agent 审核估值请求、fixture 与桥接／单位修复后接受；聚焦 fixture 检查 14 passed，共享模型＋估值 fixture 回归 28 passed。证据仅覆盖 schema 与 hand calculation，不表示估值引擎已实现。

**T030 audit evidence**：主 agent 审核估值引擎、来源与测试修复后接受；最终 valuation＋model 回归 54 passed（valuation 40、models 14）。证据仅覆盖纯计算；较早全套 431 passed 不代表并行 expression 改动后的最终全套，CLI 集成留 T033。

**T031 audit evidence**：主 agent 审核持仓研究 Skill、估值／判断方法、能力清单与 packaging 后接受；packaging 4 passed，relative links／static 检查通过。证据仅覆盖离线方法与打包，未证明原生 Bot 行为。

**T032 audit evidence**：主 agent 审核报告正文／附件原子固化、previous Decision 结构差异、MemoryPacket 内容／索引哈希与历史复原修复后接受；Decision records 25 passed，artifact＋Decision＋CLI 103 passed，含 T050／T051 recall 的受影响检查 127 passed，artifact／CLI／memory／source 扩展回归 165 passed。证据仅覆盖本地合成文件与契约，不证明报告语义、live 数据或原生 Bot 行为。

**T033 audit evidence**：主 agent 审核两券商只读路由／typed snapshot、估值输入冻结／Calculation 发布、memory 可得性及最终 failed-source snapshot guard 后接受；最终 integration 10 passed，最后 source／CLI owning slice 83 passed；较早受影响回归 314 passed 属于 guard 前修订。证据仅覆盖 MockTransport／fake SDK 与合成文件，不证明 live 券商、OAuth、账户完整性、云端或原生 Bot 行为。

**T028 audit evidence**：主 agent 审核 Longbridge OAuth 只读适配器、已安装 4.5.0 SDK stub 与最终回归后接受；聚焦检查 28 passed，broker＋两适配器 84 passed，共享模型＋broker＋两适配器 98 passed。证据仅为离线 fake-SDK／schema；live OAuth、账户覆盖、fund ISIN market 规范化及 plain-list history 完整性仍明确受限，未接 CLI。

## Phase 6: US1 — 供应链探索 (P1)

**Goal**：从主题而非固定公司名单出发，发现、验证或排除候选。

**Independent Test**：给主题与资料，输出需求—瓶颈—公司暴露—利润／估值—反证及后续验证点，允许无合格机会；可用独立材料，不要求真实持仓。

- [X] T035 [US1] 在 `fixtures/scenarios/supply-chain/cases.json` 和 `tests/integration/test_supply_chain_artifacts.py` 建立只有主题、候选被反证淘汰、证据冲突与无机会的样例，逐项定义支持结论所需出处；程序检查不冒充语义验收（依赖 T004、T032）。
- [X] T036 [P] [US1] 改写 `bot-kit/tasks/supply-chain.md` 并创建 `bot-kit/skills/supply-chain-research/SKILL.md`，落实 Serenity 方法、替代路径与范围内自主扩展，移除固定候选数和层数；任务前读记忆、后写判断与摘要（依赖 T035）。
**T036 audit evidence**：主 agent 审核供应链任务、supply-chain-research Skill、加载清单和打包名单后接受；固定候选数和层数已移除。`tests/integration/test_packaging.py` 与 `tests/integration/test_supply_chain_artifacts.py` 合并执行 13 passed、1 skipped（目录 symlink 权限），退出码 0。证据仅为 Windows 离线方法与打包，不证明原生 Grok 供应链研究或金融语义。
- [X] T037 [P] [US1] 改写 `bot-kit/tasks/company-thesis.md`，明确业务敞口、竞争／产能响应、兑现时点、估值预期及最强反证；调用 valuation 方法而不复制新公式，区分早期线索与可研究候选（依赖 T035）。
**T037 audit evidence**：主 agent 审核 company-thesis v1.0：业务敞口、竞争与供给响应、兑现时点、估值方法移交、最强反证，以及 early lead 与可研究候选的区分；未复制估值公式，已移除 “at most three”。该文件随后被纳入发布 allowlist。证据仅为离线方法文本，不证明原生研究。
- [X] T038 [US1] 在 `bot-kit/skills/research-entry/SKILL.md` 集成探索→公司验证→适用估值→反证复核的方法组合；运行 T035 的产物检查，记录在 `data/validation/us1-synthetic.md`，不得把无候选结果判执行失败（依赖 T036、T037、T030）。
**T038 audit evidence**：主 agent 审核 research-entry 的探索→公司验证→适用估值→反证复核链，以及无候选 / `no_opportunity` 记为 `WorkRecord.outcome: complete`。T035 产物检查与打包合并执行 13 passed、1 skipped（目录 symlink 权限），退出码 0。记录写在本机 `data/validation/us1-synthetic.md`。证据仅为 Windows 离线合成，不证明原生 Grok 供应链研究。
- [X] T039 [US1] 在本机由幕僚长委派无父会话子 agent，用非模板主题材料验证发现、补证边界、商业兑现与反证，记录 `data/validation/us1-chain.md`（依赖 T038）。
Evidence: local Cursor / subagent specialist on synthetic materials in `data/validation/us1-chain.md` (US limited / HK complete / quality recheck pass); not native Grok, not live.

**T035 audit evidence**：主 agent 审核四类合成供应链样例、三市场映射、事实／观点／推断区分及真实归档链路后接受；最终聚焦检查 10 passed。此前 104 项相关回归仅适用于审计修复前修订。证据仅覆盖合成样例、结构和不可变产物，不证明金融语义、原生 Grok 自主研究或 9 个现场案例。

## Phase 7: US3 — 单票因子挖掘 (P1)

**Goal**：允许当前运算组成新假设，程序计算并验证增量，不退回逐公式开发。

**Independent Test**：冻结合格数值表，用首次提出的合法表达和参数执行研究，证明没有改程序、无未来泄漏并可得“无增量”结论。数据粒度是参数，日频只是首例。

- [X] T040 [US3] 在 `tests/contracts/test_factor_requests.py`、`fixtures/factors/expected.json` 编写新组合、不同 bar_interval、未来泄漏、零除、数据修订和无增量样例；定义时间分割、精度、基准与试验计数预期（依赖 T004、T006、T017、T022）。
- [X] T041 [US3] 在 `src/cash_research/calculations/expression.py` 实现结构化表达验证、字段／单位／参数检查和运算解析，拒绝代码字符串／负 lag／未来窗口；批量资源上限可配置、可拆批，不能新增固定研究范围（依赖 T040）。
- [X] T042 [P] [US3] 在 `src/cash_research/calculations/operators.py` 与 `tests/unit/test_operators.py` 实现 calculations 契约的基础／条件／时序／滚动／EWM 运算；窗口与缺失语义显式，截断未来不改变过去（依赖 T041）。
- [X] T043 [P] [US3] 在 `src/cash_research/calculations/time_alignment.py` 与 `tests/unit/test_time_alignment.py` 实现 asof_value／event_age、可得时间、修订、公司行动及粒度／时段对齐；没有合格历史拒绝验证，不凭日期伪造 PIT（依赖 T041）。
- [X] T044 [P] [US3] 在 `src/cash_research/calculations/trials.py` 与 `tests/unit/test_trials.py` 实现实验方案冻结、表达／输入版本、参数变体、失败／弃用与 replay_of 记录；保存完整冻结 request_ref／request_hash，核对 horizon／parameter_sets／primary_metric 与复算一致；看过结果后修改必须计入新尝试（依赖 T041）。
- [X] T045 [US3] 在 `src/cash_research/calculations/factor.py` 与 `src/cash_research/calculations/validation.py` 集成计算、按时间分割／标签重叠剔除、仅训练拟合、基准、跨时段和适用成本／依赖序列区间估计；最终留出看过后不能继续当未见样本（依赖 T042—T044）。
**T045 audit evidence**：2026-09-22 本机 Cursor。`factor.py` 与 `validation.py` 按冻结请求计算因子、按时间分区并剔除标签跨区样本、训练拟合与验证选参分开、基准差、跨分区稳定性、成本与块抽样区间。最终留出被查看后状态不是 unseen。交易模拟不支持时只给研究统计。`pytest tests/unit/test_factor_validation.py tests/integration/test_factor_experiment.py tests/contracts/test_factor_requests.py -q --tb=line` 退出码 0，28 passed。证据等级 local Cursor，不是 live 或原生 Grok。
- [X] T046 [US3] 完成 `tests/unit/test_factor_validation.py` 和 `tests/integration/test_factor_experiment.py`，覆盖手算、复权事件、时间截断、折间泄漏、试验计数、无增量及不能支持交易模拟时的限制，证明相同输入可复算（依赖 T045）。
**T046 audit evidence**：2026-09-22 同一命令 28 passed。覆盖手算对照、未来截断前缀不变、折间标签剔除、复权/asof 样例、试验计数、基础设施重试不新增研究试验、无增量结论，以及相同输入可复算。
- [X] T047 [US3] 改写 `bot-kit/tasks/factor-study.md` 与 `bot-kit/skills/factor-research/SKILL.md`，允许已批准运算上的新公式／参数，明确经济机制、失败条件和验证解读；移除“无注册因子 ID 就退开发”，保留真正缺新原语／数据时的说明（依赖 T046、T013、T023）。
**T047 audit evidence**：2026-09-22 本机 Cursor。`bot-kit/tasks/factor-study.md` 与 `bot-kit/skills/factor-research/SKILL.md` 允许已批准运算上的新公式和参数，写明经济机制、失败条件和验证解读；已去掉固定注册因子 ID 退开发和最多两个注册变量。缺新原语或数据时单独说明缺口。`no_factor_increment` 不是执行失败。Skill 已加入 README、install.ps1 与 packaging allowlist。`pytest tests/integration/test_packaging.py -q --tb=line` 退出码 0，3 passed，1 skipped（目录 symlink 权限）。证据等级 local Cursor，不是原生 Grok，也不代替 T048 的 CLI。
- [X] T048 [US3] 在 `src/cash_research/cli.py` 接 compute factor，补齐 `fixtures/requests/factor-new-combination.json`，验证请求→冻结记录→计算表→Bot 解读→记忆回写，不运行模型临时生成的代码（依赖 T047、T022；与 T033 修改同一 CLI 时由负责人顺序集成）。
**T048 audit evidence**：2026-09-22 本机 Cursor。`compute factor` 读取 `fixtures/requests/factor-new-combination.json`，冻结实验、写出计算表和解读，样本不足时不写记忆；`no_factor_increment` 且指标非空时按提案回写 topic 版本。缺数据集退出码 2，不伪造成功。`pytest tests/integration/test_factor_experiment.py tests/contracts/test_cli.py -q --tb=line` 退出码 0，51 passed。证据等级 local Cursor，不是 live 历史或原生 Grok。
- [X] T049 [US3] 在本机用合格合成或已导入历史表完成一个新组合的独立专员解读，记录 `data/validation/us3-factor.md`。不要求云端或 live 历史（依赖 T048）。
**T049 audit evidence**：2026-09-22 本机 Cursor / subagent specialist。无父会话专员按 factor-research 方法解读合成新组合 `factor-new-combination`：主指标 null、样本不足、交易模拟不支持、已查看留出区不作未见样本，结果记 limited，不写成无增量或执行失败。记录 `data/validation/us3-factor.md`。不是 live 历史，也不是原生 Grok。

**T040 audit evidence**：主 agent 审核因子请求契约与 hand-calculated fixtures 后接受；聚焦检查 12 passed，共享模型＋来源＋因子契约回归 38 passed，并通过 compile／diff 检查。证据仅覆盖合同、样例和手算预期，不表示因子引擎或完整实验已实现。

**T041 audit evidence**：主 agent 审核结构化表达 parser 与 exact-number／单位／深度修复后接受；expression＋factor contract＋共享模型聚焦 114 passed，报告修订全套 533 passed。证据不表示数值因子结果或 PIT 数据已验证。

**T042 audit evidence**：主 agent 审核数值／条件／时序／滚动／EWM 运算及 one-pass EWM 修复后接受；聚焦检查 40 passed，受影响回归 140 passed。证据覆盖离线纯运算；报告中的全套 609 passed 仅适用于当时修订，不表示后续并行改动后的当前全套。

**T044 audit evidence**：主 agent 审核不可变实验请求、试验／replay 记录、留出区暴露收据、完整来源绑定及篡改防护后接受；聚焦检查 28 passed，受影响回归 180 passed。报告中的全套 654 passed 仅适用于当时修订；证据覆盖本地合成记录与程序契约，不表示完整因子实验执行已实现。

## Phase 8: US6 — 复盘、压缩与实际再注入 (P1)

**Goal**：在基础读写上完成有用经验的沉淀、失效与跨任务使用；不是此时才开始使用记忆。

**Independent Test**：可用预置判断独立复盘，含重复、矛盾、过时、跨措辞案例；新会话使用正确经验，长期能续研，假设变更能回查重评。

- [X] T050 [US6] 在 `fixtures/scenarios/periodic-delta/cases.json`、`fixtures/scenarios/long-term-thesis/cases.json`、`fixtures/scenarios/deep-analysis-revision/cases.json` 与 `tests/unit/test_memory_recall.py` 固定相关／重复／无关／失效／反证／跨标的样例和预期；加入旧材料在截止点后才被总结、旧版本后来被停用及历史版本缺失案例，分别检查 current／historical／review；不以文本相同或涨跌代替记忆效果（依赖 T004、T011）。
- [X] T051 [P] [US6] 完善 `src/cash_research/memory.py` 的别名／主题／方法检索、按 known_at 与来源 available_at 的截止时点版本选择、当时有效性及复盘两区隔离和材料预算，无法容纳关键条件时返回索引与回查路径；通过 T050 的检索检查，不将无命中视为读取失败（依赖 T050）。
- [X] T052 [P] [US6] 完善 `bot-kit/skills/research-memory/SKILL.md` 的提炼、去重、保留反证与条件、按任务选择压缩及实际使用说明；无变化不重复创造教训，单次成败不能升级为通用规则（依赖 T050）。
- [X] T053 [P] [US6] 改写 `bot-kit/tasks/retrospective.md` 与 `bot-kit/templates/review.md`，明确到期／触发检查、当时依据与后来事实分离、错误归因及下一验证点；明确原判断与后续事实两区、使用原始 memory_packet_refs，复盘草稿经 check artifact --archive 取得 Review ID 后再写经验；不新建复盘调度器（依赖 T050）。
- [X] T054 [US6] 在 `tests/integration/test_memory_roundtrip.py` 验证摘要版本冲突、记忆失效、来源引用、期限与现行指令优先；将 T051—T053 集成到 `bot-kit/skills/research-entry/SKILL.md`，所有研究方法共享同一读写能力（依赖 T051—T053、T032）。

**T054 audit evidence**：主 agent 审核 CLI 记忆往返：版本冲突保留历史后再合并、失效经验不进入当前检索、来源缺失与归档篡改失败、无 files hash 的 Decision 不得作为干净可用记忆、deep-analysis fixture 的形成时点排除、缺版本失败、冻结原 packet 与后期反证分区、预算索引仍可回读条件／来源／反例。`tests/integration/test_memory_roundtrip.py` 6 passed，退出码 0。research-entry 已通过 research-memory 共用同一读写路径，含现行指令优先、expiry、no_change 与冲突后按新 expected_version 合并。证据仅为 Windows 离线合成 CLI，不证明原生再注入或复盘实用性。
- [X] T055 [US6] 在本机对已接入方法做有／无记忆对照，并由无父会话子 agent 按简报使用召回结果；记录 `data/validation/us6-memory.md`。不要求 Routine（依赖 T054、T038、T048）。
Evidence: local Cursor CLI + subagent specialist in `data/validation/us6-memory.md` (empty recall no_history → apply version 1 → recall thesis; with-packet specialist adopt/complete vs without-packet none/limited); not Routine, not native Grok.
- [X] T056 [US6] 用至少三条合成判断在本机完成复盘链，记录 `data/validation/us6-reviews.md`；不足到期条件不假判成功，弱或失效经验不冒充事实（依赖 T055、T053）。

**T056 audit evidence**：2026-09-22 本机 Cursor CLI。三条合成判断经 `check artifact --archive` 归档，记录 `data/validation/us6-reviews.md`。not_due：`rec_692dbe8f94d54c9ca63ffc7af6cd802b`，期限未到且未把原判断写成成败。due_later_fact：`rec_47308ebffee142e0936bea334f6c3c95`，后续事实与冻结原判断分开，无事后交易。lesson_not_fact：`rec_65f9a463bdbf473887867a3e9b3ba3a4`，`lesson_refs` 为空，单次结果不升为事实。六次归档退出码均为 0。证据等级 local Cursor，不是原生 Grok。

## Phase 9: Cross-Cutting — 整体验收与交付

目标：对齐完整 spec，解决暴露的问题，不能只交付文档／接口／受限报告就结束。

- [X] T057 按 `fixtures/scenarios/manifest.json` 在本机用合成案例与独立子 agent 补齐可运行记录，写入 `data/validation/core-cases.json`；材料不足的格子写明缺口。不要求目标 Grok 环境（依赖 T034、T039、T049、T056）。
**T057 audit evidence**：2026-09-22 本机 Cursor。`data/validation/core-cases.json` 记录九格：美／港／A 股供应链与美股持仓、港股合成持仓、美股因子为 pass；A 股持仓、港股因子、A 股因子为 gap（没有对应合成持仓或历史表）。证据等级 local Cursor，不是 live 或原生 Grok。
- [X] T058 在本机验证八类异常、材料诱导、零订单、凭证／账户非公开边界、两任务并发和失败重跑，记录 `data/validation/exception-cases.json`。不要求云端定时 Routine（依赖 T033、T038、T048、T054）。
**T058 audit evidence**：2026-09-22 本机 Cursor。八类异常记录在 `data/validation/exception-cases.json`。范围变更由 `classify_scope` 处理：无模板的授权内问题继续；授权列表里的市场外请求和六个既有来源之外的供应商（含把 bloomberg 写进授权列表）返回 ask_user，不执行扩大后的请求。`pytest tests/unit/test_scope_change.py -q --tb=line` 退出码 0，5 passed。零订单与凭证不回显见 config／CLI／broker 契约测试；失败重跑见 `data/validation/us4-task-c-fail.md` 与 `us4-task-c-retry.md`；两任务分属见 `us4-task-a.md` 与 `us4-task-b.md`；材料诱导见港股连接器与 `us1-cn-reducer.md` 的冲突保留。不是 live，也不是定时 Routine。
- [x] T059 在本机按 `docs/deployment.md` 核对打包与安装说明可复走，记录 `data/validation/deployment.md`。不变更无关 Routine，不启用通知，不要求目标云端配置（依赖 T057、T058）。
- [X] T060 更新 `README.md`、`bot-kit/README.md`、`specs/001-investment-research-framework/quickstart.md` 并补全 `scripts/run_fixtures.py` 的整套验证调用后实际复走安装与调用说明；六份请求模板由 T011/T022/T029/T032/T048 提供，runner 用返回 ID 填回引用，无须手改文件；将描述统一为真实实现，明确来源缺口、维护／清理方式和实际版本（依赖 T059）。
**T060 audit evidence**：2026-09-22 本机 Cursor。`README.md`、`bot-kit/README.md`、`quickstart.md` 改为本地 0.1.0 实现说明，不声称原生 Grok、live 券商或云端安装。`python scripts/run_fixtures.py --root tmp/fixture-run-t060 --case all` 退出码 0，六步均执行：ingest/recall/valuation/archive/apply 为 ok，factor 为 partial（样本不足，与 expected 的 null directional_accuracy 对照 matched）。估值对照 matched。返回 ID 由 runner 填入后续请求。记录在 `tmp/fixture-run-t060/runs/fixtures/20260922T085730Z-4c1bfe05ce/step-results.json`。packaging 3 passed、1 skipped。G-01—G-08 仍是缺口。
- [ ] T061 持续更新 `specs/001-investment-research-framework/acceptance.md` 的脱敏 FR／SC 证据映射和未执行／受阻／通过项；从 T004 骨架起即可维护，不等待完整案例通过；此任务仅在 T057—T060 全部完成且所有 SC 通过后勾选并宣布完成，否则保留具体阻塞，不能静默改标准或采购新源（报告维护依赖 T004；最终关闭依赖 T057—T060）。

## Dependencies & Execution Order

依赖表示实施任务先后。按 TD-08，本次开发的验证任务以本机 Cursor 证据勾选，不因 live 或云端保持未完成。

```text
T001 → T002（覆盖事实与缺口）
T003 → T004 + T005…T011（最小公共能力）
  → US4 T012…T016（原生测试入口）
  → US5 T017…T025（现有数据与补证）
  → US2 T026…T034（持仓/估值 MVP）
  → US1 T035…T039（供应链）
  → US3 T040…T049（因子）
  → US6 T050…T056（完整记忆效果）
  → T057…T060（全市场及最终交付）
T004 → T061（验收汇总可持续更新；最终勾选另需 T057…T060 通过）
```

该图为推荐主线，不要求无依赖任务等待整个前一故事。实际前置以任务行和下表为准；`T018—T023` 表示闭区间全部任务，非任选一个。

| 故事 | 可以独立开始的条件 | 完整现场验收依赖 |
| --- | --- | --- |
| US4 | T011；实际配置需 T001 | 本机 T016；全部研究跨入口再由 T057—T058 验证 |
| US5 | T011、T004；适配器可离线并行 | 本机 T025；G-01—G-08 沿用 T002 缺口说明 |
| US2 | T011、T004，券商和数值测试可先做 | T033 集成；本机 T034 合成往返 |
| US1 | 公共产物／判断与估值可用；不需要真实持仓 | 本机 T039 子 agent 链 |
| US3 | T017／T022 数据契约／导入与公共模型可用；不依赖供应链结果 | 本机 T049 合成或已导入历史 |
| US6 | T011 即可用预置判断启动，和其他研究故事并行 | 本机 T055—T056 |

## Parallel Examples

仅在共同前置完成后并行，不用 `[P]` 绕过依赖：

| 故事／批次 | 可并行任务 | 原因 |
| --- | --- | --- |
| US4 | T013 与 T014 | 入口／交接方法和报告／复核文本分文件 |
| US5 | T018、T019、T020、T021、T022、T023 | 现有源适配器、导入器、补证 Skill 分文件；T024 统一接 CLI |
| US2 | T027、T028、T029 | 两券商与估值样例互不写同文件；T033 统一集成 |
| US1 | T036 与 T037 | 供应链方法与公司验证任务分文件 |
| US3 | T042、T043、T044 | 数值运算、时间对齐、试验记录分模块；T045 集成 |
| US6 | T051、T052、T053 | 检索实现、压缩方法、复盘文本分文件；T054 集成 |

若跨故事并行，`cli.py` 与 `artifacts.py` 仍按任务依赖顺序提交合并；不能同写。测试、实现、现场验证分开分工，但任何任务打勾都必须附对应结果，不能以子 agent 声称完成代替检查。

## Requirements and Acceptance Coverage

| 范围 | 实现任务 | 主要验收任务 |
| --- | --- | --- |
| FR-001—002 开放范围与三市场 | T013、T023、T031、T036—T038、T047 | T034、T039、T049、T057 |
| FR-003—004 供应链探索与候选验证 | T030、T035—T038 | T039、T057 |
| FR-005—007 综合判断／价格／券商 | T026—T033 | T034、T057、T058 |
| FR-008—010 单票因子与验证 | T040—T048 | T046、T049、T057 |
| FR-011—014 多类来源／追溯／补证／结果区分 | T006—T007、T017—T024 | T025、T057、T058 |
| FR-015—019 原生运行／充分岗位方法／确定性与统一交付 | T009、T012—T015、T030、T041—T048 | T016、T046、T058 |
| FR-020—021 历史判断与分类型记忆 | T010—T011、T032、T050—T054 | T055—T056、T057 |
| FR-022 只读与秘密边界 | T005—T008、T026—T028 | T058、T061 |
| SC-001 九个完整案例 | 三类研究故事 | T057；数据缺口格子不得降格通过 |
| SC-002 八类异常 | 各故事异常路径 | T058；独立于 T057 数据完整性阻塞 |
| SC-003 所有关键依据可定位 | T007、T022、T032、T044 | T034、T039、T049、T057、T061 |
| SC-004 专员隔离父会话 | T012—T014、各研究 Skill | T016、T039、T049、T057 |
| SC-005 数值可复算 | T029—T030、T040—T046 | T033、T046、T061 |
| SC-006 定时／并发／重跑／真实持仓 | T016、T027—T034 | T034、T058（实际定时触发而非仅 Test run） |
| SC-007 复盘与记忆实用性 | T010—T011、T050—T054 | T055—T057 |
| SC-008 零订单与无泄露 | T005、T007、T026—T028 | T058、T061 |

任务总量与分阶段结构以上述任务行为准；`[P]` 任务仍须先满足各行前置条件。完成状态以复选框及 `acceptance.md` 的分级证据为准，不用静态汇总数字替代实际记录。

## Implementation Strategy and Completion

先做已有环境／来源的轻量清点，再做最小公共能力和原生入口样例。首个 MVP 是有券商真实输入、补证、可复查估值及最小记忆的持仓判断，不是泛用数据平台。后续补齐供应链、因子和全部记忆效果，最终满足整个 spec。

资源上限与材料预算沿用 plan 的“用样例测量并写入配置”策略，本轮不新增固定候选数、模型版本、上下文 token 或性能阈值。代码变更先查当前实现与相应 spec；涉及结构查询按项目图工具规范，归档只参考，不能改写其快照。

已通过主 agent 审核的本地／离线任务按复选框和验收记录标记；按 TD-08，本机 Cursor 验证通过即勾选；证据等级仍写明 local Cursor，不冒充 live 或原生 Grok。运行时数据缺口允许独立研究继续，但最终完整案例不降格；只有用户改变要求才修改验收标准。任务完成后不自动推送或执行订单。
