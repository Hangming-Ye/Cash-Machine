# 验收映射

本文件从 T004 起持续记录验收状态。状态使用 `not_run`、`blocked`、`pass` 或 `fail`；只有链接到对应证据等级的实际产物才能改为 `pass`。文档检查、synthetic/mock、真实数据和原生 Grok 行为分别记录，不能互相替代。

## 当前实施前置状态

| Task | 状态 | 证据等级 | 记录 |
| --- | --- | --- | --- |
| T001 | pass | 原生 UI + Bot 自报环境清点 | 2026-09-22 原生 Grok UI 0.57.1 可见既有云端／源码路径；私有 `data/preflight/t001-native/config/bot-mapping.json` 与 `data/preflight/t001-native/data/preflight/environment.md` 记录替换前 Bot/Routine 快照。Bot 自报 Debian 13、Python 3.13.5、uv 0.12.15、44 个托管 Skill 文件及空 workflows，未取得独立原始命令日志。新 Bot 实际部署访问、Skill 调用及完整 Routine 登记留 T016。Bot 的 `uv run` 探测违反只读要求，在旧源码根创建 `.venv` 并获取 build dependencies；完整范围及完成程度未知且未清理 |
| T002 | pass | 本地 live 只读 + 公开补证 | 私有 `data/preflight/t002-local/source-coverage.json` 记录六个既有来源的成功／部分成功／明确错误及 G-01—G-08。长桥 OAuth 直连账户／持仓读取成功，但自选与项目适配器归一化未验证；IBKR Flex 为不完整的只读快照；港股 00700 原始／qfq 序列可追溯导入但不证明 PIT／公司行动完整。状态为 `recorded_with_gaps`，不等于完整案例通过 |
| T003 | pass | Windows 离线工程 | `uv sync --locked` 成功同步 25 packages；包与核心依赖导入成功。云端兼容性仍留 T016 |
| T004 | pass | Windows synthetic scaffold | 主 agent 已接受 skeleton；9/8/3/6 manifest、conftest `9 8 3`、`py_compile`、runner `--help`、缺模板 exit 2/`not_run`、capture/path-escape probe 与 `git diff --check` 通过。完整链和数值 expected 对照未执行，留后续任务/T060 |
| T005 | pass | Windows 离线测试 | 聚焦配置测试 17 passed；未加载 live 凭证，不证明云端配置可用 |
| T006 | pass | Windows 离线契约测试 | 主 agent 审核模型／测试；合并检查 30 passed，`uv lock --check` 与 `compileall` 通过；无 live/native 结论 |
| T007 | pass | Windows 离线产物测试 | 主 agent 审核 artifacts 实现／测试；22 passed 与 `git diff --check` 通过，覆盖悬空引用及草稿竞态拒绝；无 live/native 结论 |
| T008 | pass | Windows 离线 CLI 契约 | 主 agent 审核并接受；七组命令、统一 JSON envelope、0/2/3、partial/empty/error、全组秘密拒绝和假空仓防护包含在 33 passed 聚焦测试中 |
| T009 | pass | Windows 离线 CLI 入口 | 主 agent 审核并接受；33 passed 聚焦、最终 T005—T009 合并 85 passed，lock/sync/compileall/console help/diff check 通过；未接入的处理器明确 unsupported |
| T010 | pass | Windows 离线记忆存储 | 主 agent 审核并接受；13 passed 聚焦（含真实进程竞争），相关合并 48 passed；无原生 Grok 记忆效果结论 |
| T011 | pass | Windows 离线记忆往返 | 主 agent 审核代码、Skill 和模板并接受；完整回归 110 passed；未证明原生 Grok 记忆使用效果 |
| T012 | pass | 本机 Cursor 文档审查 | 2026-09-22 六个 prompt 均为 v1.0，README 加载清单对应；未另建 roles/ 或第二份 common。按 TD-08 不要求 Bot 运行时加载 |
| T013 | pass | Windows 离线 Skill／模板审查 | 主 agent 审核研究入口 Skill、任务简报与静态路径并接受；原生调用留 T016 |
| T014 | pass | Windows 离线报告／复核审查 | 主 agent 审核报告模板、复核任务和语义 diff 后接受；手机／PC 同结果留 T016 |
| T017 | pass | Windows synthetic 来源契约 | 主 agent 审核共同来源契约；12 passed 聚焦、25 passed 来源＋共享模型回归；无 live source 结论 |
| T026 | pass | Windows synthetic 券商契约 | 主 agent 审核并接受；25 passed broker 聚焦、56 passed config＋models＋brokers 回归；无 SDK、OAuth、Flex 或真实持仓证据 |
| T015 | pass | Windows 离线 packaging | 主 agent 审核安装／部署／fail-fast 修复；4 passed；云端安装、回滚和原生入口留 T016 |
| T016 | pass | 本机 Cursor | 2026-09-22 子代理专员交接：`data/validation/us4-entry.md`（us4-task-a/b complete 分归属；c-fail 缺材料失败、c-retry complete）；非云端／Routine／手机 PC／原生 Grok |
| T018 | pass | Windows MockTransport 来源适配 | 主 agent 审核 Finnhub 适配器；30 passed 聚焦、42 passed T017＋Finnhub 回归；无 live/persist/CLI 结论 |
| T019 | pass | Windows MockTransport 来源适配 | 主 agent 审核 Tiingo 适配器；32 passed 聚焦、44 passed T017＋Tiingo 回归；无 live/persist/CLI 结论 |
| T020 | pass | Windows MockTransport 来源适配 | 主 agent 审核 FMP stable 适配器；16 passed 聚焦、28 passed T017＋FMP、42 passed 共享模型相关回归；无 live/persist/CLI 或精确 PIT 结论 |
| T021 | pass | Windows 离线来源适配 | 主 agent 审核 AKShare 适配器与修复；27 passed 聚焦、39 passed T017＋AKShare、101 passed 三适配器＋T017 回归；无 live/CLI 结论 |
| T022 | pass | Windows 离线导入适配 | 主 agent 审核实现、fixture 与测试；24 passed 聚焦、50 passed 来源＋共享模型回归；不透明文件仅归档，无语义／PIT／CLI／持久化结论 |
| T023 | pass | Windows 离线方法／packaging | 主 agent 审核补证 Skill、事件方法、活动清单与 allowlist；4 passed packaging，静态链接／旧上限／diff 检查通过；无 native web、live source 或 CLI 路由结论 |
| T024 | pass | Windows 离线来源集成 | 主 agent 审核 router／CLI／ID／持久化／记忆出处；最终聚焦 140 passed、受影响 memory＋source 44 passed；较早 159/396 不作为并行改动后的最终全套结论，无 live/native 结论 |
| T025 | pass | 本机 Cursor | 2026-09-22 pytest 133 passed，记录 `data/validation/us5-sources.md`；公开材料补证由 `test_primary_failure_then_imported_substitute_is_durable_and_referenceable` 覆盖；G-01—G-08 沿用 T002，未重复 live 探测；非 live API／原生网页 |
| T040 | pass | Windows synthetic 因子契约 | 主 agent 审核请求契约及 hand-calculated fixtures；12 passed 聚焦、38 passed 共享模型＋来源＋因子契约回归，compile／diff 通过；无因子引擎或完整实验结论 |
| T041 | pass | Windows 离线表达解析 | 主 agent 审核 parser 及 exact-number／unit／depth 修复；expression＋factor contract＋models 114 passed，报告修订全套 533 passed；不证明数值因子或 PIT 完整性 |
| T027 | pass | Windows MockTransport 券商适配 | 主 agent 审核 IBKR Flex 适配器及 cutoff／时区／覆盖修复；31 passed 聚焦、56 passed broker＋IBKR、70 passed 共享模型相关回归；无 live Flex/saved-query 结论 |
| T028 | pass | Windows fake-SDK 券商适配 | 主 agent 审核 Longbridge OAuth 适配器、4.5.0 SDK stub 与回归；28 passed 聚焦、84 passed broker＋两适配器、98 passed 共享模型相关回归；无 live OAuth/account/CLI 结论 |
| T029 | pass | Windows synthetic 估值契约 | 主 agent 审核估值请求、fixture 与桥接／单位修复；14 passed 聚焦、28 passed 共享模型＋fixture 回归；仅 schema／手算，无估值引擎结论 |
| T030 | pass | Windows 离线估值计算 | 主 agent 审核引擎及 signed net debt／Decimal／sensitivity／输入一致性修复；valuation＋models 54 passed；纯计算，CLI T033 pending |
| T031 | pass | Windows 离线持仓研究方法 | 主 agent 审核 Skill／估值与判断方法／能力清单及 packaging；4 passed packaging，relative links／static 通过；无 native Bot 结论 |
| T034 | pass | 本机 Cursor | 2026-09-22 合成持仓往返 pytest 133 passed，记录 `data/validation/us2-portfolio.md`；confirmed empty 与 failed read 不混淆，失败不发 snapshot；未读真实账户 |
| T050 | pass | Windows synthetic 记忆契约 | 主 agent 审核 seed proposals 及真实 temporal／review／budget API 测试；8 passed 聚焦、16 passed baseline-related；相关性检索仍属 T051 |
| T051 | pass | Windows 离线记忆检索 | 主 agent 审核 metadata／temporal／dedupe 与正反证券匹配；16 passed 最终聚焦，前一修订 29 models／59 memory＋source；无 native reinjection 结论 |
| T052 | pass | Windows 离线记忆方法 | 主 agent 审核 consolidation／dedupe／compression／apply API 文本；packaging 4 passed 及 static checks；无语义效果结论 |
| T053 | pass | Windows 离线复盘方法 | 主 agent 审核 retrospective／Review template／archive request 文本；packaging 4 passed 及 static checks；无 native Review 流程结论 |
| T054 | pass | Windows 离线记忆往返 | 主 agent 审核 CLI roundtrip 与 deep-analysis fixture 等价；6 passed；无 native reinjection 结论 |
| T036 | pass | Windows 离线供应链方法 | 主 agent 审核方法、Skill 与打包；合并检查 13 passed、1 skipped；无 native 供应链研究结论 |
| T037 | pass | Windows 离线公司验证方法 | 主 agent 审核敞口、供给响应、兑现时点、估值移交与反证；无公式复制；无 native 结论 |
| T038 | pass | Windows 离线供应链入口 | 主 agent 审核方法链与 T035 产物检查；13 passed、1 skipped；记录 `data/validation/us1-synthetic.md`；无 native 结论 |
| T039 | pass | 本机 Cursor | 2026-09-22 子代理合成链记录 `data/validation/us1-chain.md`（US liquid-cooling limited／HK connector complete；质量复核先 revise 后双 pass）；非原生 Grok、非 live |
| T043 | pass | Windows 离线时间对齐 | 主 agent 审核完整 A／B／C 实现及最终公司行动出处修复；最终聚焦 18 passed，最终出处修复前相关计算／契约回归 159 passed；仅证明合成输入上的时点、修订、时段及复权资格检查，不证明 live 数据具备 PIT 完整性 |
| T045 | pass | 本机 Cursor | 2026-09-22 `factor.py`／`validation.py`：冻结请求计算、时间分区与标签跨区剔除、训练拟合与验证选参分开、基准差、跨分区稳定性、成本与块抽样区间；最终留出查看后非 unseen；交易模拟不支持时仅研究统计。`pytest tests/unit/test_factor_validation.py tests/integration/test_factor_experiment.py tests/contracts/test_factor_requests.py -q --tb=line` 退出码 0，28 passed；非 live／原生 Grok |
| T046 | pass | 本机 Cursor | 2026-09-22 同一命令 28 passed；覆盖手算对照、未来截断前缀不变、折间标签剔除、复权／asof 样例、试验计数、基础设施重试不新增研究试验、无增量结论、相同输入可复算；非 live／原生 Grok |
| T047 | pass | 本机 Cursor | 2026-09-22 factor-study／factor-research：已批准运算上新公式与参数、经济机制、失败条件、验证解读；无注册因子 ID 退开发与双变量上限；缺口单独说明；`no_factor_increment` 非执行失败；Skill 已入 README／install／packaging；packaging 3 passed、1 skipped；非原生 Grok，不代替 T048 CLI |
| T048 | pass | 本机 Cursor | 2026-09-22 `compute factor` 读 `factor-new-combination.json`：冻结实验、写出计算表与解读；样本不足不写记忆；`no_factor_increment` 且指标非空时回写 topic 版本；缺数据集 exit 2。`pytest tests/integration/test_factor_experiment.py tests/contracts/test_cli.py -q --tb=line` 退出码 0，51 passed；非 live 历史／原生 Grok |
| T049 | pass | 本机 Cursor | 2026-09-22 专员解读合成新组合，记录 `data/validation/us3-factor.md`；outcome `limited`（主指标 null／样本不足／交易模拟不支持／留出已查看不作未见）；非无增量、非执行失败；非 live／原生 Grok |
| T055 | pass | 本机 Cursor | `data/validation/us6-memory.md`：空召回 vs version 1；有记忆包专员 adopt／complete vs 无 packet limited；非 Routine／原生 Grok |
| T056 | pass | 本机 Cursor | three rec_ ids and not_due / later fact / lesson not fact. |
| T057 | pass | 本机 Cursor | nine-cell file; three gaps named, not treated as pass. |
| T058 | pass | 本机 Cursor | 2026-09-22 八类异常见 `data/validation/exception-cases.json`；范围变更／零订单／凭证边界／失败重跑／两任务分属／材料诱导已记录；非 live、非定时 Routine |
| T059 | pass | 本机 Cursor | 2026-09-22 本机 Cursor。按 `docs/deployment.md` 打包 `tmp/releases/cash-research-0.1.0-candidate-20260922.zip`，SHA-256 `00c942d30d2b922712046f3b99e143a024b2bf41b7b138a98bc5e10c5aeae625`，90 个载荷文件。清单哈希核对通过。在解压目录内 `uv sync --locked --python 3.12` 后 `cash-research --help` 退出码 0。packaging 测试 3 passed、1 skipped（WinError 1314）。zip 不含 sec-analysis.env、.env 或 data/。未改云端、Routine 或通知。记录 `data/validation/deployment.md`。非云端安装 |
| T060 | pass | 本机 Cursor | six-step fixture chain exit 0, factor partial matched expected null metric. Not native Grok. |

## SC-001—SC-008

| 标准 | 当前状态 | 所需证据 | 当前记录／阻塞 |
| --- | --- | --- | --- |
| SC-001 三类能力 × 三市场的 9 个完整案例 | blocked | 9 个完整研究产物及逐项验收 | 本机 Cursor：`core-cases.json` 有 6 个本地 pass 格与 3 个缺口（CN portfolio、HK factor、CN factor）；缺口不计为 pass |
| SC-002 8 类异常 | pass | 每类执行记录、补证尝试及后续动作 | 本机 Cursor：本文件 8 类异常行均为 pass，含 `tests/unit/test_scope_change.py` |
| SC-003 可追溯性 | blocked | 关键事实、价位和因子结果的来源／时间／口径／计算定位 | 本机 Cursor：本地已有归档决策、因子计算回执与记忆版本，但本周期未对全部九案的每个价位与因子主张做逐项审计 |
| SC-004 三类专员隔离执行 | blocked | 目标 Grok 环境、产品版本、可见模型信息和实际交付 | 本机 Cursor：供应链与因子子代理简报已在无父聊天下运行；未另开持仓专员会话；非原生 Grok |
| SC-005 确定性计算可复查 | pass | 预先声明精度、冻结输入和重复计算结果 | 本机 Cursor：T060 fixture 运行中估值 expected 对照匹配；因子重算与 null `directional_accuracy` 匹配 `fixtures/factors/expected.json` |
| SC-006 既有环境定时／并发／重跑／只读持仓 | blocked | 原生定时、两个并发范围、失败重跑、手机 PC 同结果、只读持仓进入输入 | 本机 Cursor：本开发周期不以定时 Routine、手机/PC 或 live 持仓读取为完成条件，且均未跑。本地并发与重跑证据见 `data/validation/us4-task-a.md`、`us4-task-b.md`、`us4-task-c-fail.md`、`us4-task-c-retry.md`；不可称为定时触发 |
| SC-007 复盘、记忆和实用性 | pass | 至少 3 条复盘、压缩／失效／再注入及三类记忆场景对照 | 本机 Cursor：`data/validation/us6-reviews.md` 中 3 条归档复盘；`data/validation/us6-memory.md` 中空召回 vs version 1 |
| SC-008 零订单与零敏感泄露 | pass | 全验收运行的操作及公开产物审计 | 本机 Cursor：拒单与秘密不回显见 `tests/unit/test_config.py`、`tests/contracts/test_cli.py`、`tests/contracts/test_brokers.py`；非对每份报告的完整公开产物审计 |

## 案例登记

### 9 个核心案例

| Case | 市场 | 类型 | 状态 | 证据等级 | 证据路径 |
| --- | --- | --- | --- | --- | --- |
| core-us-supply-chain | US | 供应链 | not_run | synthetic mapping | — |
| core-hk-supply-chain | HK | 供应链 | not_run | synthetic mapping | — |
| core-cn-supply-chain | CN | 供应链 | not_run | synthetic mapping | — |
| core-us-portfolio | US | 持仓／自选 | not_run | synthetic mapping | — |
| core-hk-portfolio | HK | 持仓／自选 | not_run | synthetic mapping | — |
| core-cn-portfolio | CN | 持仓／自选 | not_run | synthetic mapping | — |
| core-us-factor | US | 因子 | not_run | synthetic mapping | — |
| core-hk-factor | HK | 因子 | not_run | synthetic mapping | — |
| core-cn-factor | CN | 因子 | not_run | synthetic mapping | — |

### 8 类异常

| Case | 异常 | 状态 | 证据等级 | 证据路径 |
| --- | --- | --- | --- | --- |
| exception-preferred-source-failure | 首选源失败 | pass | 本机 Cursor | `tests/integration/test_source_fallback.py` |
| exception-critical-source-conflict | 关键源冲突 | pass | 本机 Cursor | supply-chain conflicting-evidence plus `data/validation/us1-cn-reducer.md` |
| exception-insufficient-history | 历史不足 | pass | 本机 Cursor | `tests/unit/test_factor_validation.py` |
| exception-no-qualified-opportunity | 无合格机会 | pass | 本机 Cursor | supply-chain no-qualified-opportunity case |
| exception-no-factor-increment | 无因子增量 | pass | 本机 Cursor | `tests/integration/test_factor_experiment.py` |
| exception-scope-change | 范围变更 | pass | 本机 Cursor | `tests/unit/test_scope_change.py` |
| exception-invocation-failure | 调用失败 | pass | 本机 Cursor | `data/validation/us4-task-c-fail.md` |
| exception-broker-read-failure | 券商读取失败 | pass | 本机 Cursor | `tests/integration/test_portfolio_research.py` |

### 记忆样例

| Case | 场景 | 状态 | 证据等级 | 证据路径 |
| --- | --- | --- | --- | --- |
| memory-periodic-delta | 定时增量 | not_run | synthetic mapping | — |
| memory-long-term-thesis | 长期主题续研 | not_run | synthetic mapping | — |
| memory-deep-analysis-revision | 重分析与修订 | not_run | synthetic mapping | — |

## 更新规则

- `blocked` 必须写明具体环境、数据或依赖阻塞；独立工作继续推进。
- `pass` 必须记录产品／程序／配置版本、输入定位、数据时点、命令结果和证据路径。
- synthetic/mock 结果只证明离线契约或计算，不证明真实数据权限、研究实用性或原生 Grok 行为。
- 受限案例不能计入 SC-001 的 9 个完整案例。只有 SC-001—SC-008 及 T057—T060 的适用证据全部通过后，T061 才能完成。

## 2026-09-22 研究深度说明

同日修订引入 A-07 与 US1／US2 多阶段深度要求后：本文件中历史 local／synthetic 通过行仍为当时证据等级下的历史记录，不予改写为 pass 或 fail。这些记录（含 T039 本地链与同日现场筛查）不满足 A-07 及修订后的 US1—US2 完成标准；后续以未勾选的 T062—T064 及更新后的验收映射另行证明。不在此翻写旧 SC 行状态。
