# 个人投研平台数据源设计（美股 / A股 / 港股）

> 调研日期：2026-09-20（Asia/Shanghai）。本文核验的是公开官方文档、产品页和条款；未登录、未购买、未调用任何数据接口，因此所有账号权限、字段覆盖和稳定性均为**未实测**。搜索结果或网页可见不等于 API 可取，更不等于获准保存全文。

## 结论先行

当前交接已经覆盖了“美股日线、通用行情/新闻、标准化基本面、A股公开网页数据、券商账户流水”这几块，但真正影响 24/7 多 Bot 投研质量的缺口仍有六个：

1. **三地官方披露直连**：SEC、巨潮、HKEXnews 应成为事实层，第三方标准化数据只能做索引和计算层。
2. **可回溯的 PIT（point-in-time）**：多数便宜 API 只给“当前修订后值”；回测必须保存首次披露、后续更正、抓取时点和供应商修订链。
3. **美股卖方研报全文与三地一致预期修订历史**：FMP/Finnhub 只能快速起步，当前方案没有获授权的美股投行研报全文，也没有被验证为可重建任一历史时点 consensus 的 vintage 库；中国卖方明细、报告全文授权和预测修订轨迹同样缺失。不要把新闻聚合、评级变化或“当前 consensus”伪装成研报库或历史时点可见数据。
4. **电话会/IR 全文与事件流**：Quartr 是清晰的增量源；它覆盖实时/历史音频、转录、报告、演示稿和 webhook，价格需询价，适合付费升级而非首日依赖。
5. **中国主观信息的合规机器入口**：财联社、财新、华尔街见闻的公开产品均面向阅读或订阅，未见面向个人 Bot 的公开全文 API；只能存元数据、链接和人工订阅状态。新闻聚合可提示事件，不能替代获授权的深度正文、卖方观点或社交原帖，也不能把网页抓取当正式数据管道。
6. **供应链量价与行业先行指标**：公开财报无法替代运单量、贸易流向、能源产销量及价格、宏观 vintage 数据。FRED/ALFRED 与 EIA 能补公开宏观和能源量价，但不能给出企业级客户供应商关系；Panjiva/ImportGenius 能补运单与实体关系，却不是天然 PIT 库，也不等同于完整成交价格。只有明确的行业假设再买其中一个。

一期已明确不接 Longbridge 行情。其公开文档显示 OpenAPI 可提供行情与账户接口，但具体市场权限、历史深度和账户 entitlement 尚未登录实测；因此这里只列作未来可选项，不改变一期 Finnhub 报价方案，也不把它设为当前报价主源。[Longbridge Pricing](https://open.longbridge.com/pricing) [Quote 文档](https://open.longbridge.com/docs/cli/market-data/quote)

## 25 个来源/工具的实际增量

“全文”指接口或产品明确提供正文/转录；“元数据”指标题、时间、标识符、摘要或链接。价格仅记录官方公开页上对架构决策有意义的档位。

| # | 来源 / 工具 | 可获得内容与形式 | 历史、时效与 PIT | 权利 / 成本 / 结论 |
|---:|---|---|---|---|
| 1 | **SEC EDGAR** | 美国申报全文、提交历史、Company Facts/XBRL；JSON 与 bulk ZIP | submissions 通常低于 1 秒、XBRL 通常低于 1 分钟；夜间 bulk；`accepted` 时间可作知识时点 | 免费、无需 API key，须标识 User-Agent 并遵守 10 req/s 公平访问。美国披露**主权威源**。[API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) [Fair Access](https://www.sec.gov/about/developer-resources) |
| 2 | **巨潮资讯 CNINFO** | A股法定披露平台；公告查询和 PDF 全文；调研、问询、监管等 | 网页按公告时间发布；能保存原公告时间，但公开页没有承诺稳定的开发者 API 或历史修订 SLA | 免费网页适合检索/下载官方 PDF；正式自动化应询价 CNINFO Data Service。不要依赖未公开网页接口。[公告查询](https://www.cninfo.com.cn/new/fulltextSearch) [官方身份](https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?checkedCategory=category_rcjy_szsh&url=disclosure%2Flist%2Fsearch) |
| 3 | **HKEXnews / HKEX IIS** | 港股公告、上市文件、权益披露；IIS 是上市公司消息实时 feed | 公共 HKEXnews 适合事实核验；IIS 面向实时分发并有传输规范 | 公共网页/PDF 与授权实时 feed 是两条路线。港股披露**主权威源**，实时生产应采购 IIS 而非爬网页。[IIS](https://www.hkex.com.hk/Services/Market-Data-Services/Infrastructure/Issuer-Information-feed-Service-%28IIS%29?sc_lang=en) |
| 4 | **Tiingo** | 美股/中国股票 EOD、拆分分红、调整价；另有 IEX、新闻、基本面 | 美股 EOD 多在 17:30 ET，可持续接受交易所更正至 20:00；可返回原始及调整价；基本面更新通常落后 SEC 12–24h | 个人 Starter $0，Power $30/月；个人数据仅内部使用，展示/再分发另议。保留现选职责：**一期美股历史日线主源**；新闻/基本面仍由现有分工处理。[EOD](https://www.tiingo.com/documentation/end-of-day) [Pricing](https://app.tiingo.com/pricing/) [License](https://www.tiingo.com/documentation/general) |
| 5 | **Finnhub** | 报价、新闻、财务、预期、SEC、电话会、演示稿、供应链等；REST 与官方 OAuth MCP | 各数据集不同；当前值、延迟标签和历史字段是否含修订历史需按一期账号逐项验收 | 保留现选职责：**一期报价以及全球新闻/事件**。MCP 调用仍计入 Finnhub 限额，字段可能因套餐不可用；未实测前不把产品目录中的每一类能力视为已开通。[官方 MCP 数据目录](https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html) |
| 6 | **Financial Modeling Prep (FMP)** | 标准化三表、指标、报价、新闻、预期、评级、电话会全文、SEC 索引 | 历史深度按档位；返回值中可保存 filing/accepted 时间的接口才可用于 PIT，不能默认所有标准化值均 PIT | Basic 免费 250 次/日；年付 Starter/Premium/Ultimate 公开价 $19/$49/$99 每月；展示/再分发需单独许可。保留为**跨市场标准化基本面与初级预期**。[Docs](https://site.financialmodelingprep.com/developer/docs) [Pricing](https://site.financialmodelingprep.com/developer/docs/pricing) |
| 7 | **AKShare** | Python 聚合公开网站的中港美行情、财务、公告、热度、资金流等 | 源网页变化会导致接口失效，文档明确要求频繁升级；通常不保留供应商修订历史 | 保留现选职责：**一期中国市场主数据入口**。其免费开源和公开网页聚合属性意味着必须监控字段、缺失率和抓取时间，并回链巨潮/HKEX 官方披露；官方风险提示称仅用于学术研究并提示商业风险。[项目说明](https://akshare.akfamily.xyz/introduction.html) [数据字典](https://akshare.akfamily.xyz/data/index.html) |
| 8 | **Tushare Pro** | A股日线、财务、预告、股本、资金、互动易、券商研报与盈利预测；HTTP/Python | 日线盘后更新，财务随公告更新；部分接口含 `ann_date`/`first_ann_date`，有利于 PIT | 官方页公开了个人积分与部分专项数据价格。它是 **AKShare 服务等级、字段稳定性或 PIT 能力不满足后的候选升级**，不是一期替换决定。[权限/价格](https://tushare.pro/document/1?doc_id=290) [字段示例](https://tushare.pro/document/2?doc_id=45) |
| 9 | **Longbridge OpenAPI** | OAuth 账户资产、持仓、订单、成交、基本面、新闻及 US/HK/CN 行情能力 | 实时推送/REST；各市场权限、历史深度和账户 entitlement 需登录实测 | 一期不接其行情。未来若需要同一券商账户的持仓/成交读取或行情，可单独做只读 PoC；OpenAPI 行情权限与 App 权限分开，未实测前不推定可用范围。[OAuth](https://open.longbridge.com/docs/how-to-access-api) [Positions](https://open.longbridge.com/docs/trade/asset/stock) |
| 10 | **IBKR Flex** | 自定义 Activity Statement / Trade Confirmation，TEXT/XML | 可查询当前年及前四个日历年；天然是券商账本，不是实时行情源 | 负责**已成交、现金、费用、税务、日终对账**；保持只读及 T+1 流程。[Flex Queries](https://www.ibkrguides.com/clientportal/performanceandstatements/flex.htm) |
| 11 | **Quartr API** | 16,000+ 公司、65 市场；实时/历史音频与转录、报告、演示稿、事件摘要；REST/webhook/Snowflake | 提供事件、文档更新时间和 webhook，适合构建变更流；历史音频/全文明确可用 | 企业询价；内部使用和再分发条款分开。它是**电话会与 IR 文档**最清晰的付费增量，不替代官方申报。[Docs](https://quartr.com/docs/introduction) [Pricing](https://quartr.com/pricing) [Terms](https://quartr.com/terms-of-service) |
| 12 | **东方财富 Choice + 妙想** | Choice 有全维度数据库、Python 接口、研报/盈利预测；妙想是建立在公告、研报、数据、舆情上的投研问答 | 数据可实时/日频；PIT 和原始版本能力须合同验收 | 机构产品询价。妙想是分析层，不是可复制的数据授权；已有 Grok 多 Bot 时优先买 Choice 数据接口，而不是再买一个黑盒问答层。[Choice](https://www.choice-china.com/guide.html) [妙想说明](https://choice.eastmoney.com/choicewebfile/UserGuide.pdf) |
| 13 | **同花顺 iFinD Data API** | HTTP/SDK；高频、实时/历史行情、证券信息、财务与盈利预测 | 支持 token/refresh token，Linux/Windows 与多语言；具体历史和修订取决于指标 | 机构询价。若 A/H 研究重且需要可编程全量数据，可在 Wind/Choice/iFinD 中**三选一**试用，不要全买。[HTTP 示例](https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/example.html) [FAQ](https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/help-center/faq.html) |
| 14 | **Wind Client API** | 中港美及全球基本面、权益事件、财务业绩、盈利预测、新闻舆情、风险事件、800万+ 宏观指标 | 历史日线/Tick/分钟回放；是否提供可重建的估计修订 vintage 需合同验收 | 高价机构询价。只有当跨资产/中国数据广度成为核心壁垒时再升级；个人平台不宜首购。[Client API](https://www.wind.com.cn/portal/zh/ClientApi/index.html) |
| 15 | **通联数据 DataYes** | 传统+另类数据、量化因子、风险模型、新闻/公告/研报搜索、盈利预测与知识图谱 | 官方称 50 年+ 回溯、全天候生产；具体 PIT/频率/表权限依合约 | 机构询价。适合量化、组合与知识图谱一体化，但与现有多 Bot/RAG 重叠较大；仅在需要成品因子/风险模型时选。[产品](https://www.datayes.com/) [方案](https://www.datayes.com/solution.html) |
| 16 | **朝阳永续 Go-Goal** | A/H 卖方研报、分析师原始预测、一致预期、季度业绩前瞻、研报向量库 | 核心价值是卖方明细和多年沉淀；可从明细计算预测分歧/修订，PIT 字段需样本验收 | 机构询价。若主要缺口是**中国卖方预测修订**，它比再买一个综合终端更有增量。[产品](https://www.go-goal.com/) [季度预测说明](https://www.go-goal.com/dynamic/277043) |
| 17 | **财联社** | 7×24 电报、深度解析、付费“电报解读/风口研报”；网页/APP 阅读 | 当前快讯实时；公开产品未见稳定个人 API 或历史全量导出承诺 | 订阅用于**人工阅读与链接跳转**；Bot 只保存标题、时间、URL、访问级别。不要把公开网页抓取当正式全文源。[官方介绍](https://www.cls.cn/our) [产品页](https://www.cls.cn/index) |
| 18 | **财新 / 财新数据通** | 高质量原创财经新闻、宏观/公司数据库、Excel 工具、舆情预警 | 7×24 资讯；深度数据和下载需订阅 | 个人会员明确禁止机器人/爬虫获取及非个人使用。适合作为人工二次核验，不进入自动全文仓。[FAQ](https://database.caixin.com/help/) [付费条款](https://database.caixin.com/vip/) |
| 19 | **华尔街见闻** | 7×24 全球市场要闻、VIP 深度内容、课程 | 当前/历史阅读存在，但未见面向个人 Bot 的公开全文 API | 仅存元数据与链接；有全球宏观新闻价值，但与 Finnhub 新闻重叠，基线不接自动管道。[App](https://wallstreetcn.com/download) [会员](https://wallstreetcn.com/member/help) |
| 20 | **X API** | 最近 7 天搜索、2006 年以来全量搜索（付费/Enterprise）、帖子/用户/互动等结构化字段 | 最近搜索所有开发者可用；全量历史付费；离线保存后须持续跟随删除/修改，收到 X 或账户所有者请求后最迟 24h 处理 | 现为按量计费，帖子读取 $0.005/条，月上限 300 万条（超过用 Enterprise）。适合确定性规则、可审计原始 ID 流。[Search](https://docs.x.com/x-api/posts/search/introduction) [Pricing](https://docs.x.com/x-api/getting-started/pricing) [Policy](https://docs.x.com/developer-terms/policy) |
| 21 | **Grok Bot X connector / xAI API `x_search`** | Grok Bot 官方 X connector 可搜索帖子、读时间线、查 mentions；独立 xAI API 的 `x_search` 还能按关键词、语义、用户、线程和日期检索并返回引用 | 两者都是实时研究入口，不应假定为完整 firehose 或可重放语料 | 一期优先使用 **Grok Bot 官方 X connector**；官方说明需在 Grok Bot 登录该 connector，付费用户获得初始 X API credits。独立 xAI API 是后续显式服务，需 API key 并在请求中声明 `x_search`，不能因使用 Grok 产品而推定自动开通。[Grok Bot + X](https://x.ai/news/grok-bot-and-x) [x_search](https://docs.x.ai/developers/tools/x-search) |
| 22 | **Reddit Data API** | subreddit/post/comment 搜索与讨论全文（OAuth） | 适合事件后讨论，不是交易所级实时源；历史完整性与删除同步需自行处理 | 非商业、合理用量可能免费；商业/超限需单独协议。条款禁止未经权利人许可用用户内容训练 AI，并要求只保留获批用途所需数据。仅作低权重情绪旁证。[Terms](https://redditinc.com/policies/data-api-terms) [官方说明](https://redditinc.com/news/apifacts) |
| 23 | **FRED / ALFRED** | 宏观序列、发布日、series vintage dates；REST JSON/XML | ALFRED 能查询历史时点看到的修订版本，是宏观 PIT 的关键免费来源 | API key 免费；每个系列可能有第三方版权，且现行条款限制缓存/归档和 AI 训练用途，必须逐系列看 notes/许可。用于在线查询及特征生成，不复制整库。[API](https://fred.stlouisfed.org/docs/api/fred/) [Vintages](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html) [Terms](https://fred.stlouisfed.org/legal/terms/) |
| 24 | **U.S. EIA Open Data** | 电力、石油、天然气等官方行业数据；API v2 | 官方周期更新；发布时间与观测期分开保存 | 免费 API key。能源/公用事业研究的低成本结构化事实源。[API docs](https://www.eia.gov/opendata/documentation.php) |
| 25 | **Panjiva / ImportGenius（二选一）** | 运单级进口/出口、shipper/consignee、HS/HTS、港口、重量/金额；Panjiva 有实体解析/API/Snowflake，IG 偏自助检索/下载 | Panjiva Marketplace 明示 **Point In Time: No**、延迟可变；IG 美国进口从 2006、出口从 2014（视套餐） | 有明确供应链假设再采购。Panjiva 企业询价；IG 美国套餐公开从 $229/月、Pro $449/月、全球企业 $1,999/月。不要同时买；先做 2 周单一行业试点。[Panjiva](https://www.marketplace.spglobal.com/en/datasets/panjiva-supply-chain-intelligence-%2822%29) [ImportGenius Pricing](https://www.importgenius.com/pricing) |

## 建议的来源路由与权威层级

同一事实不要“多源投票”。先指定权威源，再让其他源做发现、加速或交叉检查：

| 数据域 | 主权威 | 加速/标准化 | 冲突处理 |
|---|---|---|---|
| 美股当前/历史价格 | Finnhub 一期报价；Tiingo EOD 历史 | Longbridge 仅作未来候选 | 同一时点不同则展示 venue/session/延迟标签，不做平均；一期账号先验收实时/延迟状态 |
| A/H 当前与盘后数据 | AKShare 一期主入口 | 服务等级不满足后再评估 Tushare；Longbridge 行情仅作未来候选 | 交易所时区、币种、复权方式和盘前/盘后分开；披露事实仍回链交易所原文 |
| 美股披露 | SEC 原文与 XBRL | FMP 标准化 | 数字冲突以 accession + 原文 context 为准 |
| A股披露 | 巨潮原公告 | AKShare 一期抽取；服务等级不满足后评估 Tushare | 保存首次公告和更正公告关系，不覆盖旧值 |
| 港股披露 | HKEXnews / IIS | FMP/Quartr 仅索引或抽取 | 以 HKEX 发布时间和原 PDF 为准 |
| 持仓/交易/现金 | IBKR Flex 日终 | 内部组合账本；Longbridge 账户读取仅作未来只读 PoC | 经纪商流水覆盖模型推算，差异进入 reconciliation queue |
| 标准化财务 | FMP | 官方披露回链校验 | 不带 source document/filing date 的值不得进入回测 |
| 美国/全球预期 | FMP 起步 | 高要求时在 Finnhub 与机构源中选一个做样本验收 | consensus 必须带 as-of、样本数、币种、年度口径 |
| 中国卖方预期 | 一期无已验证的权威库 | AKShare 只做发现；服务等级不足后评估 Tushare，深度需要时评估朝阳永续 | 保留 analyst/report/published_at/revision，不只留均值；聚合新闻不能填补该缺口 |
| 电话会/IR | 公司 IR/官方申报；付费 Quartr | FMP 转录可作低成本起步 | 音频/稿件版本、speaker、事件时间均需保存 |
| 全球新闻 | Finnhub 标题/摘要/URL | 财联社/财新/华尔街见闻只做人读链接 | 原始媒体发布时间优先于聚合器抓取时间 |
| 社交 | Grok Bot 官方 X connector 做研究型检索 | 后续显式接入 xAI API `x_search`；需要确定性原始流才启用 X API；Reddit 为旁证 | 社交永远不能覆盖官方事实，只产生待验证线索 |
| 宏观/行业 | FRED/ALFRED、EIA | 供应链专题再选 Panjiva 或 ImportGenius | 同时记录 observation period、release time、vintage |

## 24/7 多 Bot 的数据契约

每条对象至少保存四类时间，缺一项就不能称为 PIT：

- `event_time`：事件发生或财报涵盖的经济时点。
- `published_at`：原始来源公开时间（SEC 用 acceptance time；公告用交易所发布时间）。
- `source_updated_at`：供应商更正/更新时点。
- `retrieved_at`：本系统实际看到并写入的时点。

原始层 append-only，不用新值覆盖旧值。建议核心字段为：

```text
source_id, source_native_id, canonical_url, issuer_id, security_id,
content_type, access_level(metadata|snippet|fulltext|structured),
event_time, published_at, source_updated_at, retrieved_at,
valid_from, valid_to, revision_of, payload_hash, license_scope,
market, currency, timezone, session, parser_version
```

Bot 路由建议：

1. `filing-us/cn/hk` 只接官方披露，输出 immutable document 与结构化 facts。
2. `market-account` 一期接 Finnhub 报价、Tiingo 历史和 IBKR Flex 日终账本，禁止下单；Longbridge 只保留未来只读 PoC 位置。
3. `fundamentals-estimates` 一期接 FMP 与 AKShare，并强制回链官方文档；无 as-of 的估计只用于当前看板。Tushare 是服务等级不满足后的候选。
4. `news-social` 一期接 Finnhub 与 Grok Bot 官方 X connector，Reddit 只作旁证；只生成“线索”，不直接改写财务事实。独立 xAI API `x_search` 是后续服务。
5. `evidence-verifier` 将线索提升为 `verified`，至少需要官方/公司原文或两条真正独立来源。
6. `thesis-monitor` 只读取已验证事实、价格和持仓，计算 prove/kill/catalyst 状态。
7. `mobile-notifier` 接收去重后的高优先事件；推送显示“事实 / 推断 / 情绪”标签、来源链接和数据时点。

### 去重与“情绪回声”

- 文档去重：优先原生 ID（accession、announcement ID、HKEX document ID、post ID）；没有 ID 才用规范化 URL + 正文哈希。
- 事实去重：`issuer + metric + period + unit + scope` 是同一事实族；新值创建 revision edge，不覆盖。
- 新闻聚类：`实体集合 + 规范化标题 + 90 分钟窗口 + 关键数字`，同时保留 `derived_from/quoted_from/syndicated_from` 边。
- 情绪只在**最早独立原文**计一次。聚合器、转帖、引用同一通讯社、同一公司新闻稿都标为 echo，不能把转发量当作多条独立证据。
- 社交分数拆成 `original_authors`、`unique_threads`、`reposts`、`independent_links`；展示扩散强度和观点方向，但不合成一个虚假的“置信度”。
- 每个摘要保存 `evidence_ids[]`、模型/提示版本和引用 URL；全文权限不足时只给“标题级判断”，UI 必须显示 `metadata_only`。

## 采购顺序

### 便宜基线（先跑通）

1. 保留现选：Tiingo 负责美股 EOD 历史，Finnhub 负责一期报价及全球新闻/事件，FMP 负责标准化财务和当前预期。
2. 接 SEC、巨潮、HKEXnews 官方原文；这是最大质量提升，成本接近零。
3. IBKR Flex 继续做日终账本。一期不接 Longbridge 行情；未来确有账户或行情整合需求时，再对 OAuth、市场权限和只读范围做 PoC。
4. 保留 AKShare 作为一期中国市场主入口，监控字段变化、缺失率和更新延迟；只有服务等级、稳定性或 PIT 能力不满足时再评估 Tushare，不预先替换。
5. Grok Bot 优先登录官方 X connector，只查高价值 watchlist/事件窗口并设置使用预算。独立 xAI API `x_search` 与直接 X API 都是后续显式接入项。
6. FRED/ALFRED 与 EIA 只按策略所需系列查询，保存许可说明与 vintage。

这套组合暂不采购 Wind/Choice/iFinD/DataYes，也不自动摄取财联社/财新/华尔街见闻全文；它只覆盖一期日常价格、披露、组合账本、基础财务、新闻与轻量社交线索。美股投行研报全文、历史一致预期、中文深度主观内容和企业级供应链量价仍是明确缺口。

### 付费升级（缺什么买什么）

- 电话会和全球 IR 文档经常缺失：买 **Quartr**，并逐步停用 FMP 的转录职责。
- 中国卖方预测修订/报告级数据成为核心：买 **朝阳永续**；若同时需要跨资产综合终端，再在 Wind/Choice/iFinD/DataYes 中做一个带样本验收的选择。
- Grok Bot connector 的交互式检索不能满足可编程研究时，再显式接入 **xAI API `x_search`**；只有确定性 X 历史与规则回测需要原始帖子时，才启用 **X API** 并实现内容删除/修改同步。
- 某个行业的进口、出口、客户供应商关系能直接验证投资假设：先试 **ImportGenius 单一区域**；若需要实体解析、API/Snowflake 与全球关联，再升级 **Panjiva**。

所有升级都应先用固定的 20 个标的、10 个历史事件验收：覆盖率、首发延迟、历史深度、修订可重建性、全文权利、导出/API 限额、取消后的数据保留权。没有通过这七项，不进入生产路由。
