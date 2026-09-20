# 供应链瓶颈投研 Skill 与数据工具调研

研究日期：2026-09-20  
目标：为个人投资 Grok Bot 设计“从产业主题发现供应链卡点，并尽早找到可投资上市公司”的研究支柱。本报告只讨论研究与监控，不包含自动交易执行。

综合审查补充：下文“三关”约束的是投资行动成熟度，不应阻挡早期发现。研发/送样/认证阶段可先进入早期线索池，带领先指标和下一验证点；只有买入研究需要继续通过利润和估值检验。主架构已明确线索与投资两种产物，不要求先确认收入才关注。

## 结论

`serenity-skill` 适合作为研究提问框架和报告模板，但不能单独成为供应链研究引擎。它当前最有价值的部分是：先排产业链层级，再查公司；区分研发、送样、认证、量产、订单、交付和确认收入；把“产业卡点”“公司能否赚到钱”“估值是否已经反映”分开。它没有实际采集器、实体解析、供应链数据库、产能数据库、估值计算器或持续监控状态。

建议采用四层组合：

1. **方法层**：吸收 `serenity-skill` 的问题拆解、证据阶梯、反方检验和备忘录结构。
2. **证据图层**：建立带时间、来源和置信度的需求—部件—工艺—产能—公司—客户—替代路线图；可参考 `chokepoint-atlas` 的图概念，但不要复制其未授权代码；优先复用 MIT 许可的 SOFA、`stock-relation`、`alphasig` 中合适的实现。
3. **数据层**：SEC/交易所/公司披露为主证据，OpenBB 提供行情和标准财务接口，ImportYeti/Panjiva/FactSet 等用于验证关系和物流。商业数据只能作为接入服务，不能随产品重新分发。
4. **判断层**：分别输出瓶颈强度、利润捕获、估值计价三组结论，不压成一个看似精确的总分。只有三关都通过，才进入“优先研究/候选买入区间”阶段；否则保留为产业线索或观察对象。

## 对 `muxuuu/serenity-skill` 的实际仓库审阅

仓库：[muxuuu/serenity-skill](https://github.com/muxuuu/serenity-skill)。本次按 `main` 分支于 2026-09-20 读取，未执行仓库脚本。

### 它实际提供什么

- [`SKILL.md`](https://github.com/muxuuu/serenity-skill/blob/main/SKILL.md) 当前标注版本 `1.1.0`、MIT，定位是供应链瓶颈研究方法。主链条是“系统变化 → 供应链位置 → 公司真实暴露 → 利润捕获 → 估值和时点 → 反方理由”。它明确指出上游、冷门或逆向本身不构成高优先级。
- [`deep-research-workflow.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/deep-research-workflow.md) 是最值得抽取的核心：把“核心供应商”拆成产品相关、完成认证、量产、平台供应商、收入重大、有无定价权、是否独家等不同可证伪主张。
- [`evidence-ladder.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/evidence-ladder.md) 要求记录来源日期、报告期、页码/章节、该材料能证明什么和不能证明什么，并明确“证据置信度”不等于“股票研究优先级”。
- [`market-source-playbook.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/market-source-playbook.md) 给出美股、A 股、港股、台湾、日本、韩国和欧洲的官方资料入口及市场特有风险。这是来源路由表，不是数据连接器。
- [`risk-and-compliance.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/risk-and-compliance.md) 把小盘股、社媒传播、匿名客户、融资摊薄、弱现金流、完美执行估值等列为额外核验项。
- [`public-profile-and-evaluation.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/public-profile-and-evaluation.md) 对方法来源保持谨慎：人物身份和收益多为自述或二手重复，应该复用推理路径，不复用人物权威或收益叙事。
- [`serenity-dialogue-protocol.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/serenity-dialogue-protocol.md) 适合交互式研究：每轮给当前判断、指出缺口、只问一个关键问题，然后继续向证据、估值和失效条件推进。
- [`output-style-and-language.md`](https://github.com/muxuuu/serenity-skill/blob/main/references/output-style-and-language.md) 和 [`thesis-template.md`](https://github.com/muxuuu/serenity-skill/blob/main/assets/thesis-template.md) 可直接转成 Bot 的报告契约。
- [`research-prompt-pack.md`](https://github.com/muxuuu/serenity-skill/blob/main/assets/research-prompt-pack.md) 只能作为用户入口示例，不能充当逻辑实现。
- [`evals/test-cases.md`](https://github.com/muxuuu/serenity-skill/blob/main/evals/test-cases.md) 提供行为验收思路，包括先排层级、主动查反例、用实时来源、说明下一步检查。
- [`scripts/validate_skill.py`](https://github.com/muxuuu/serenity-skill/blob/main/scripts/validate_skill.py) 只用 Python 标准库检查 frontmatter 名称、描述和目录名；它不验证研究质量，也不抓取任何数据。
- [`README.md`](https://github.com/muxuuu/serenity-skill/blob/main/README.md) 明确表示 Skill 不附带实时行情服务或数据账号，研究本身不依赖 Python，Python 仅用于维护检查。

### 可直接复用、应改写、不能指望的部分

| 部分 | 建议 | 原因 |
|---|---|---|
| `SKILL.md` 的六段研究逻辑 | 抽取并改写成内部流程状态机 | 逻辑清楚，但仍是自然语言约束，无法保证每次完整执行 |
| 证据阶梯、市场来源路由、备忘录模板 | 可在保留 MIT 版权声明后直接改造 | 与目标高度一致，字段可转成结构化 schema |
| 风险边界、对话协议、测试用例 | 改写为质量门和回归用例 | 适合验证 Agent 行为，不提供数据真实性保证 |
| `validate_skill.py` | 价值很低，可不用 | 只检查 Skill 包结构，与投研质量无关 |
| Prompt pack | 只提炼入口意图 | 提示词包含过时的“local scorecard”入口；当前 README 树和脚本仅列 `validate_skill.py`，说明仓库存在轻微文档漂移 |
| 公司名单、排名、历史示例结论 | 不复用为当前结论 | 示例有时点，不能替代最新公告、行情和估值 |

### 依赖和许可

- 仓库根 [`LICENSE`](https://github.com/muxuuu/serenity-skill/blob/main/LICENSE) 是标准 MIT License，版权为 `Copyright (c) 2026 muxu`。复制或改造实质内容时需保留版权与许可声明。
- 运行时没有捆绑数据依赖；活跃研究依赖宿主提供网页搜索、浏览器、交易所/财报或行情工具。维护脚本需要 Python 3，且当前脚本仅使用 `re`、`sys`、`pathlib` 标准库。
- MIT 只覆盖该仓库代码和文档，不自动授予 Serenity 公开帖文、交易所文件、研报、新闻、商业数据库或商标的再分发权。

## 相关 Skill、仓库与数据服务对比

“直接复用”表示可以在遵守许可证和依赖的前提下复用代码；“抽取方法”表示更适合重写成自有流程；“服务接入”表示需遵守外部账号、订阅和数据条款。

| 项目 | 实际能力 | 适合怎么用 | 依赖/费用 | 许可与注意点 |
|---|---|---|---|---|
| [muxuuu/serenity-skill](https://github.com/muxuuu/serenity-skill) | 主题拆链、证据阶梯、公司挑战、报告模板 | 抽取方法；作为研究编排的上层契约 | 宿主搜索/财报/行情能力 | MIT；不含采集和估值代码 |
| [wesson9527/chokepoint-atlas](https://github.com/wesson9527/chokepoint-atlas) | 更完整的图 schema、研究包、赛道比较、催化剂监控脚本；[`graph-schema.md`](https://github.com/wesson9527/chokepoint-atlas/blob/main/references/graph-schema.md) 定义系统/部件/公司/证据/催化剂节点，[`catalyst-watch.md`](https://github.com/wesson9527/chokepoint-atlas/blob/main/references/catalyst-watch.md) 定义持续跟踪 | 只借鉴概念后独立实现 | 本地 Python 脚本及外部材料 | **仓库根未见 LICENSE 文件，默认不能复制、修改或分发其代码/文本**；必须取得授权或只学习抽象思想 |
| [Rainnystone/SOFA](https://github.com/Rainnystone/SOFA) | 可持续 OSINT 研究工作区、证据/主张台账、阶段门、反方审查、Ticker Dive/Sector Hunt；入口见 [`skills/sofa-analyze/SKILL.md`](https://github.com/Rainnystone/SOFA/blob/main/skills/sofa-analyze/SKILL.md) | 直接复用状态管理、台账和质量门；裁掉重型多 Agent 流程后接入本 Bot | Python；搜索/行情能力为推荐而非硬依赖 | MIT；流程很重，原样采用会显著增加时间和 token 成本 |
| [supat-roong/stock-relation](https://github.com/supat-roong/stock-relation) | 从 SEC 10-K/20-F 发现公司提及，以本地零样本分类器判断供应商/客户/竞争关系；FastAPI、SQLite、Qdrant、D3 图；README 说明 Gemini 用于私募/收购发现 | 复用 SEC 抓取、关系候选生成和可视化代码；所有边必须回链原文并人工/模型复核 | Docker、Qdrant、Hugging Face 模型；部分路径需 Gemini API key | MIT；分类器可能把提及误判为关系，不能直接证明产能、独家或定价权 |
| [sushaan-k/alphasig](https://github.com/sushaan-k/alphasig) | EDGAR 异步抓取、供应链关系提取、风险段落 diff、时间戳信号、NetworkX 图、DuckDB/Parquet/API/告警 | 直接复用 filing diff、时间化信号和图输出，作为美股监控器 | Anthropic API key；SEC User-Agent；Python 包 | MIT；项目较新，README 的预测性说法要独立回测，不能当成已证实 alpha |
| [anthropics/financial-services-plugins](https://github.com/anthropics/financial-services-plugins)（检视的公开 fork 页面也列出相同结构） | 财务建模、equity research、催化剂跟踪、研报输出；通过 MCP 接 Daloopa、Morningstar、S&P、FactSet、LSEG、PitchBook 等 | 抽取 equity-research/估值/盈利桥模板；有账号时接商业 MCP | 多数连接器需订阅或 API key | Apache-2.0；Skill 本身不解决供应链实体和产能数据，连接器数据受各服务条款约束 |
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | 统一行情、财务、SEC、宏观等数据接口，并可暴露 REST/MCP；[平台 README](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/README.md) 列出免费与付费 provider | 直接作为行情、估值快照、标准财务和 SEC 接口层；不承担瓶颈判断 | 免费和付费 provider 混合，不同市场覆盖不同 | AGPL-3.0；若修改并作为网络服务提供，需要认真评估 AGPL 义务；各 provider 另有数据条款 |
| [SEC EDGAR Developer Resources](https://www.sec.gov/about/developer-resources) | 免费提交历史、XBRL Company Facts、完整 filing 文本和全文搜索 | 服务接入；作为美股客户集中度、供应风险、资本开支和财务主证据 | 免费，需遵守 SEC 公平访问政策和 User-Agent 要求 | 政府公开数据不等于每条供应关系都披露；只覆盖申报内容，匿名客户和私企链条仍缺失 |
| [ImportYeti Data API](https://docs.importyeti.com/) | 美国和墨西哥海关/提单的公司、供应商、产品、航次查询；可验证实际发货方向、频次和变化 | 服务接入；做 shipment 交叉验证和异常监控，不作为独家关系证明 | 免费人工搜索；[价格页](https://www.importyeti.com/pricing/supply-chain) 显示专业版、企业版和 API/积分费用 | 商业条款；买到的数据有其专门 [Data Use Policy](https://www.importyeti.com/policies/data-use)，免费页面和批量/持续数据不适用同一承诺；海运提单不覆盖全部运输方式和内销 |
| [FactSet Revere Supply Chain Relationships](https://go.factset.com/hubfs/Website_Downloads/Statistical%20Package%20Integration/Docs%203.0/ExtractVectorFormula.pdf) | 公私公司客户、供应商、竞争者和合作伙伴的正反向关系 | 服务接入；快速扩充候选边并做反向客户检查 | 明确需要 FactSet Supply Chain 订阅 | 商业数据，不可当开源代码复制或再分发；关系存在不代表金额重大、当前有效或具有定价权 |
| [S&P Global Panjiva](https://www.spglobal.com/market-intelligence/en/solutions/products/panjiva-supply-chain-intelligence) | 海关/承运人交易、公司实体解析、产品与 HS/HTS 分类、供应链图和告警；[数据集页](https://www.marketplace.spglobal.com/en/datasets/panjiva-supply-chain-intelligence-%2822%29) 支持 API/Feed/云 | 服务接入；用于全球物流、供应商份额、产品流量和客户变化验证 | 商业订阅/询价 | 数据集页面标注 `Point In Time: No`，不能未经处理用于严格历史回测；覆盖国家和报关口径不完整，且不可重新分发原始数据 |

## 推荐的目标数据模型

### 节点

| 节点 | 必需字段 | 用途 |
|---|---|---|
| `Theme` / `DemandDriver` | 名称、地域、起止时间、可量化需求指标 | 把热点变成可测需求变化 |
| `EndSystem` | 产品/系统、架构版本、单位需求 | 例如一套系统需要哪些部件及数量 |
| `Component` / `Process` / `Material` | 规格、替代路线、认证要求、良率约束 | 找到真正受限的物理或工艺环节 |
| `Capacity` | 公司/工厂、名义产能、有效产能、利用率、良率、扩产周期、时间 | 防止把静态稀缺当成持久瓶颈 |
| `Company` | 法人实体、母子公司、地区、业务段 | 承载业务关系，避免 ticker 等同于法人 |
| `Security` | ticker、交易所、股本、币种、价格时间 | 一家公司可对应多个证券，估值必须落到证券 |
| `Customer` / `Supplier` / `Competitor` | 实体标识、关系期间、关系是否具名 | 构造上下游与替代网络 |
| `Evidence` | URL、标题、发布日期、报告期、页码/章节、原文片段哈希、抓取时间、证据等级 | 每个事实都可追溯和重新核验 |
| `FinancialMetric` | 指标、期间、口径、币种、reported/adjusted | 建立收入—毛利—现金流桥 |
| `ValuationSnapshot` | 价格日期、股本日期、EV/市值、盈利期间、共识来源 | 判断市场是否已计价 |
| `Catalyst` / `Falsifier` | 事件、预计日期、可观测阈值、影响方向 | 支持持续监控和论点失效 |
| `ThesisVersion` | 版本、截至日期、状态、改判原因 | 保留决策记忆，禁止事后改写原论点 |

### 边

至少需要以下带 `effective_from`、`effective_to`、`evidence_ids`、`confidence` 的边：

- `DemandDriver -> drives -> EndSystem`
- `EndSystem -> requires(quantity_per_unit) -> Component`
- `Component -> requires -> Process/Material`
- `Company -> produces(at_facility) -> Component`
- `Capacity -> constrains -> Component`
- `Company -> supplies -> Customer`
- `Customer -> qualifies -> Company/Product`
- `Company/Product -> substitutes_for -> Company/Product`
- `Evidence -> supports|contradicts -> Edge/Claim`
- `ComponentConstraint -> may_benefit -> Company`
- `CompanyBusiness -> contributes_to -> FinancialMetric`
- `ValuationSnapshot -> prices_expectation_for -> ThesisVersion`
- `Catalyst -> confirms|weakens -> ThesisVersion`
- `Falsifier -> invalidates -> Claim`

“可能受益”必须单列，不能把“处于卡点”直接写成“利润受益”。

## 精确研究流程

### 1. 输入和研究契约

输入：主题或公司、目标市场、研究截至日、时间窗口、允许的证券范围、是否包含现有持仓/观察池、风险偏好、数据预算。先冻结 `as_of`，后续任何来源都记录发布日期和适用期间。

输出契约：产业链图、候选全集、证据台账、三道门判断、估值情景、催化剂/失效条件、下一步核验和监控规则。缺数据时允许输出“无合格公司”。

### 2. 从需求到系统

1. 用客户资本开支、产量、装机、项目批准、终端出货等量化需求，而不是用新闻热度。
2. 把技术/政策变化翻译为系统架构变化和单位物料需求。
3. 建立主路线、替代路线和绕行方案；任何“卡点”都必须回答客户如何绕开。

验证：至少一个需求侧一手来源和一个工程/物料侧来源能连接到同一变化。

### 3. 从系统到约束

逐层记录需求量、现有有效产能、利用率、良率、扩产周期、认证周期、供应商数、库存、交期和价格。形成按季度或月度的 `demand/capacity` 区间，而不是一个静态标签。

瓶颈成立需要组合证据：需求持续、有效产能接近上限、扩产/认证慢、替代路线短期不可用。只有“供应商少”或“技术很难”不足以成立。

### 4. 从约束到公司全集

从每个受限部件双向扩展：披露的供应商、客户披露、竞争对手、海关/提单、专利/标准、扩产审批、设备采购、招聘和产业专家材料。先建立宽候选集，再映射到可交易证券；记录私企、子公司和母公司的归属关系。

验证：每条公司关系至少回到一段可打开的原文或一条交易/物流记录；模型抽取只是候选边。

### 5. 三道门，不合并为总分

**A. 业务是不是瓶颈**

- 需求/有效产能区间及变化速度；
- 实际交期、订单积压、产能预订、良率、认证周期；
- 替代供应商、客户自制和技术替代所需时间；
- 约束是全行业、局部规格、单一客户还是短期扰动。

**B. 公司能否把瓶颈变成股东利润**

- 该产品处于研发、送样、认证、量产、交付还是确认收入；
- 相关收入/订单占比、ASP、毛利率、增量毛利、利用率、资本开支和自由现金流；
- 客户集中度、长协/价格重谈、原料成本传导、客户议价和扩产融资；
- 瓶颈由公司控制，还是公司自己被上游、设备、良率或资金卡住。

**C. 股票是否已经计价**

- 用同一日期的价格、股本和净债务，对齐下一财年/周期中段盈利；
- 反推当前 EV/市值隐含的销量、ASP、份额、毛利率和持续年限；
- 与公司可实现的产能坡度、客户订单和替代路线比较；
- 记录过去 1/3/6/12 月涨幅、估值分位、分析师预期差和融资摊薄。好业务若需要“完美兑现”才能支持当前价格，应列为已计价或过度计价。

每个候选输出三元标签，例如：`瓶颈=强 / 利润捕获=未证实 / 计价=高`。这比 `82/100` 更能告诉用户下一步查什么。

### 6. 排序与受益者识别

候选优先级按门槛处理：

1. 先剔除关系证据不足、商业阶段不清或严重治理/融资风险的公司；
2. 在真实瓶颈公司中，优先有可见收入桥、增量毛利和现金流的公司；
3. 在利润捕获相近时，优先隐含预期更低、催化剂更明确且下行可描述的证券；
4. 明确列出一个热门但降级的环节，以及降级的具体理由；
5. 不为了凑数输出 3–5 家，无合格候选也是有效结论。

### 7. 催化剂、证伪和持续监控

每个论点绑定可观测事件：客户资格完成、首次量产、扩产投产、交期变化、ASP/毛利变化、客户资本开支、双供导入、库存与应收、融资/减持、政策和出口限制。监控只在以下情况触发更新：

- 新证据改变一条图边的状态或期间；
- 指标越过预设阈值；
- 催化剂到期未兑现；
- 估值进入/离开预设区间；
- 失效条件被触发。

更新时生成 thesis diff：新增/删除了哪些边，哪条主张从“线索”变成“确认/反驳”，为什么改变研究优先级。原版本不可覆盖。

## 推荐落地顺序

1. **先做 schema 和证据台账**：把 Serenity 的主张拆解、证据阶梯和 thesis 模板结构化；这是所有后续功能的约束。
2. **接官方一手源与行情估值**：美股先接 SEC + OpenBB；A/H 股分别接交易所/公司公告和可信行情源。先保证每个数有日期、期间和口径。
3. **加入关系候选生成**：优先评估 `stock-relation` 或 `alphasig` 的 MIT 代码，但所有 NLP 关系边都要求原文回链和二次确认。
4. **加入产能与物流验证**：小规模可先用公司披露和 ImportYeti 人工/API；预算充足再评估 Panjiva 或 FactSet。不要因有商业关系边就推断瓶颈。
5. **加入估值反推和 thesis memory**：从市场价格反推隐含经营假设，保存每次研究版本、催化剂与证伪条件。
6. **最后接持仓/观察池**：把研究结论映射为“买入候选、持有、观察、降低优先级”及价格区间，但保留用户确认，不连接自动下单。

## 主要风险与需验证项

- 供应链公开披露存在选择性和时滞；匿名客户、私企和二级/三级供应商会形成缺口。
- 海关/提单记录是物流证据，不等同于合同金额、独家资格、终端用途或收入确认。
- LLM/分类器发现的关系具有假阳性；必须保存原文、方向、期间和复核状态。
- 产能数字要统一名义/有效产能、良率、产品规格和工厂口径，否则 `demand/capacity` 没有可比性。
- 商业数据库的覆盖、历史可回放能力和再分发许可差异很大；Panjiva 明示其数据集不是 point-in-time，FactSet/商业 MCP 需订阅。
- `chokepoint-atlas` 当前仓库页面未显示 LICENSE；不要复制其脚本、模板或长段文本。`serenity-skill`、SOFA、`stock-relation`、`alphasig` 的 MIT 许可和 financial-services-plugins 的 Apache-2.0 仍要求保留相应声明。OpenBB 的 AGPL-3.0 需要在选择嵌入式复用还是独立服务接入前做许可证审查。
