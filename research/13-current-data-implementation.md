# 当前数据拉取实现：只读阅读记录

2026-09-20｜仓库 `main`，提交 `bc15860`（Initial import）

**用途：了解已探索的数据接口及限制，不将旧代码复用作为架构前提。** 用户已明确原实现只有部分取数功能，允许新写或低成本改造；目标工作流、数据契约和程序简洁性优先于兼容旧工程。

## 1. 已确认的实现结构

```text
Python调用：SecAnalysisClient
                           -> build_providers -> 市场/新闻/财报Router
CLI调用：Typer命令          -> build_providers -> 同一组适配器
                           -> IBKR / Longbridge只读客户端
供应商响应 -> Pydantic数据对象 -> Python对象或Rich终端表格
```

CLI不经过SecAnalysisClient，而是直接共用其底层注册器/路由。`client.py`已有quote、bars、news、company_news、fundamentals、statement、account、positions、executions和routes。它提供统一的基础读取入口，还不是研究工作流引擎。[Client](../archive/sec-analysis-20260920/src/sec_analysis/client.py) · [CLI](../archive/sec-analysis-20260920/src/sec_analysis/cli.py) · [注册器](../archive/sec-analysis-20260920/src/sec_analysis/providers/registry.py)

一期路由与README基本一致：US/HK报价与新闻走Finnhub；US日线走Tiingo；US profile/三表走FMP stable；A股报价、日线、个股新闻、三表走AKShare；IBKR主读路径为Flex，长桥为只读账户/持仓/成交。日线与报价分开配置；备选供应商按市场排列，配置错误立即终止，普通调用失败可尝试下一项。[配置](../archive/sec-analysis-20260920/src/sec_analysis/config.py) · [行情Router](../archive/sec-analysis-20260920/src/sec_analysis/providers/router.py)

## 2. 值得参考的经验

- **供应商职责划分**已有具体实现，不必从接口搜索开始。是否继续使用这些供应商仍取决于目标覆盖、权益和数据质量，调用代码无需原样保留。
- **A股回退路径**把公开源不稳定的问题具体化，可作为新适配器的故障样本和回归用例。
- **只读券商接口、OAuth/Flex接入流程**有实现与mock测试可参考；能减少重复摸索，但不表示当前账户已验证连通。
- **明确错误类型**区分ProviderConfigError与ProviderError；一期主要数据源没有密钥时不静默改成假价格。这种行为值得继续保持。[错误类型](../archive/sec-analysis-20260920/src/sec_analysis/core/errors.py)
- **注入适配器与mock测试**便于离线验证格式；研究程序可以独立设计自己的接口，不需要依赖此工程的类结构。

## 3. 对新系统有意义的边界

| 现状 | 新系统需要怎样处理 |
|---|---|
| CLI主要输出Rich表格；新闻表仅列时间、标题、来源 | 给程序/Bot稳定结构化结果，保留URL、摘要、原文定位和来源状态，不依赖终端表格解析 |
| 有Quote/Bar/Fundamental/StatementReport等对象，但没有统一的抓取时间、原始响应版本、证据ID或快照ID | 从目标任务包设计数据契约，按字段保留口径与时点；不为了复用旧models丢掉证据 |
| StatementReport沿用sina_stock/sina_symbol字段，单位转换由调用方处理；Position不含独立快照时间 | 新模型区分报表期、披露/可获知时点、单位以及账户快照时间，避免把相同as_of理解成相同含义 |
| SqliteCache仅保存bars/news/executions，Client/CLI未接入；使用INSERT OR REPLACE | 不能当作已建立的研究资料库或历史判断账本；需要另设计版本/追加语义 |
| RateLimiter仅对同一实例内线程生效，每次build_providers会新建；不同Bot/CLI进程不共享预算 | 新程序集中取数和供应商配额，不假设当前限速器能协调多Bot |
| JP/KR默认stub；部分非一期适配器未接通/会回退stub，options默认stub | 程序必须标明真实/演示/不支持；不能因有同名接口就把它登记为真实能力 |
| NewsRouter会把正常空列表和所有来源失败都收敛为ProviderError | 目标结果应区分无新增、无覆盖、未授权、失败、部分成功 |

依据：[数据模型](../archive/sec-analysis-20260920/src/sec_analysis/core/models.py)、[缓存](../archive/sec-analysis-20260920/src/sec_analysis/storage/cache.py)、[限速器](../archive/sec-analysis-20260920/src/sec_analysis/core/rate_limit.py)、[新闻路由](../archive/sec-analysis-20260920/src/sec_analysis/providers/news_router.py)、[未接适配器](../archive/sec-analysis-20260920/src/sec_analysis/providers/minimal.py)、[stub](../archive/sec-analysis-20260920/src/sec_analysis/providers/stub/__init__.py)。上述是设计输入，不要求先把旧工程修到完整再建设新系统。

## 4. 供应商与券商阅读补充

以下事实值得带入新系统的数据契约，旧代码不必先修到完备：

1. **历史行情不等于因子数据集。** Tiingo目前映射raw OHLC，成交量缺失时才回退adjVolume；A股日线显式不复权。没有保留拆股/分红事件与复权标识，不能直接用于严格收益和量价因子研究。[Tiingo映射](../archive/sec-analysis-20260920/src/sec_analysis/providers/tiingo/client.py) · [AKShare日线](../archive/sec-analysis-20260920/src/sec_analysis/providers/akshare_provider/client.py)
2. **财报不等于时点数据。** FMP只接profile及annual三表，映射排除了acceptedDate、fillingDate和原文链接；输出as_of主要是报告期。AKShare财报同样缺披露/修订时间。新系统需独立保存period_end、公开/可获知时间和版本，不能用期末日期代替发布日。[FMP](../archive/sec-analysis-20260920/src/sec_analysis/providers/fmp/client.py) · [A股财报](../archive/sec-analysis-20260920/src/sec_analysis/providers/akshare_provider/fundamentals.py)
3. **时间和底层来源会丢失。** A股新闻把无时区字符串直接标UTC，失败可落epoch；部分报价/账户/成交时间缺失或解析失败会退到抓取当下。AKShare多源回退后仍统称akshare。未来需要分开供应商原始时间、市场时区、抓取时间、时间质量和实际endpoint。[A股新闻](../archive/sec-analysis-20260920/src/sec_analysis/providers/akshare_provider/news.py) · [Flex时间](../archive/sec-analysis-20260920/src/sec_analysis/brokers/ibkr/flex.py) · [长桥映射](../archive/sec-analysis-20260920/src/sec_analysis/brokers/longbridge/readonly_client.py)
4. **账户只是局部快照。** IBKR真实读取链为Flex/T+1，Gateway/TWS仍未接；长桥按调用读取TradeContext。账户余额映射会优先选某币种行而非完整多币种总账；长桥持仓主要为数量/成本/币种，基金读取失败可被跳过。持仓时效、缺失字段和部分成功必须显式保留，不能把空字段补零作为风险计算输入。[IBKR入口](../archive/sec-analysis-20260920/src/sec_analysis/brokers/ibkr/readonly_client.py) · [长桥入口](../archive/sec-analysis-20260920/src/sec_analysis/brokers/longbridge/readonly_client.py)
5. **handoff中的长桥自选分组未在本次代码中找到。** 限定读取/检索`src/sec_analysis/brokers`及Client/CLI、相关测试，没有watchlist/group查询接口；长桥测试还禁止QuoteContext。应记为“此代码快照未提供”，不据此否定云端另有脚本或产品本身有此能力。[长桥测试](../archive/sec-analysis-20260920/tests/test_longbridge.py)

## 5. 配置与验证口径

Settings默认只读取`.env`。当前文件名`sec-analysis.env`不会被这段默认加载逻辑自动读取；部署端可能另有环境变量导入，本次未检查，也未读取该文件内容。不能仅凭本地文件存在确认接口可用。[config.py](../archive/sec-analysis-20260920/src/sec_analysis/config.py)

本轮查看源码、调用文档和相关测试；63个Python文件（46个src、17个tests）通过标准库AST语法解析。当前Python环境缺少pytest及项目依赖，本次未安装依赖、未运行单元测试、未访问金融服务、未读取账户/密钥值。mock测试表达了预期行为，不等于实盘接口验证。

源码与配置未修改。旧图谱只有handoff快照（generation `2026-09-20T09:33:47Z`），src/tests不在其记录中；本次结论使用源码读取和限定目录搜索，不将空图谱当作实现缺失证明。
