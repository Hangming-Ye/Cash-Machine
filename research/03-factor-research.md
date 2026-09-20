# 单票因子研究应先成为“证据流水线”，而不是自动找最优策略

日期：2026-09-20  
范围：基于现有 `sec-analysis` Python CLI、日频数据、人工交易决策；不下单，不设计自动交易系统。

综合审查说明：本文后续给出的年限、样本数、折数比例、统计阈值是候选实验协议，须按有效样本量、标签重叠、股票状态和用户期限调整，不是平台通用准入真理。依赖选择也是研究候选，实施前先查实际仓库环境；主架构以描述/探索/样本外支持/前瞻验证分层。

## 结论

建议第一期只增加一个轻量 `factor-research` 子系统：复用 Tiingo / FMP / AKShare 客户端，自己实现 10–15 个可解释因子、严格的时点对齐、嵌套滚动验证、成本/基准/状态压力测试，并产出一份可供人判断的 evidence packet。核心依赖只需 `pandas/numpy + statsmodels + scikit-learn + vectorbt`；实验先用本地 manifest/JSONL/Parquet 记录，达到几十到上百次实验后再接 MLflow。

不要在第一期引入 Qlib 全栈、RD-Agent 自动因子生成、FinRL/强化学习、tsfresh 全量特征或 Optuna 大搜索。这些项目有可借鉴的方法，但会把一个单票、小样本问题迅速变成高自由度搜索，增加伪发现。Qlib 的 Alpha158 和 Alphalens 主要是横截面框架，也不能原样用于单票。

真正的交付不是“找到一个 Sharpe 最高的参数”，而是回答：这个因子在什么时间可知、相对什么基准有效、扣成本后是否稳定、在哪些市场状态失效、当前观测是否落在历史支持范围内，以及证据不足时为什么应当观望。

## 1. 单票问题与横截面问题不是一回事

| 问题 | 横截面因子 | 单票时间序列因子 |
|---|---|---|
| 样本单位 | 同一交易日的多只资产 | 同一股票在不同日期的观测 |
| 典型问题 | 今天价值/动量最高的一组股票是否胜过最低的一组 | 这只股票当前状态是否提高未来 5/20/60 日的超额收益或降低下行风险 |
| 常用统计 | 日度横截面 IC、Rank IC、分位数组合、多空收益 | 滚动预测、事件条件收益、方向命中、校准、时间序列回测 |
| 标准化 | 当日股票池内去极值、排名、行业/市值中性化 | 仅用过去数据做滚动 z-score/百分位；与自身历史和市场状态比较 |
| 主要依赖 | 足够大的、当时可投资股票池 | 足够长且覆盖多种状态的完整个股历史 |

[Qlib Alpha158 的实现](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py)默认 `instruments="csi500"`，通过 `QlibDataLoader` 生成特征，标签明确是 `Ref($close,-2)/Ref($close,-1)-1`；[Qlib 文档](https://github.com/microsoft/qlib/blob/main/docs/component/data.rst)解释了这是 T+1 买、T+2 卖的交易时点选择。[Alphalens 的 tear sheet](https://github.com/quantopian/alphalens/blob/master/alphalens/tears.py)则要求 `(date, asset)` MultiIndex，并按因子分位数、去均值或行业中性化计算收益。这些方法需要同日多资产。单只股票每天只有一个横截面观测，所谓横截面 IC、分位数组合和中性化没有统计含义。

单票可以借用 Alpha158 的表达式思想，例如收益、波动、价格位置、量价关系，但必须重写为过去窗口的时间序列特征。标签也必须显式绑定决策时间：若因子在 T 日收盘后才完整可知，最早只能按 T+1 可成交价格进入，不能用 T 日收盘成交。

## 2. 14 个项目的实现核查与取舍

下表以官方仓库、源码或官方文档为准。维护状态按 2026-09-20 可见项目状态判断；Alphalens 和 Backtrader 作为常见方案保留，但明确按成熟旧项目而不是新系统基础处理。

| 项目 | 实际实现方法 | 对本项目的判断 |
|---|---|---|
| [Microsoft Qlib / Alpha158](https://github.com/microsoft/qlib) | `DataHandlerLP` 区分学习/推断处理器，`QlibDataLoader` 用表达式生成特征和未来标签；Alpha158 是预设 OHLCV/滚动算子库，并有 workflow/record 体系。 | **借方法，不引全栈。** 数据格式、交易日历和多资产范式与现有 CLI 集成成本高；提取少量可解释公式和严格标签时点即可。当前维护。 |
| [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent) | 代码不是“让 LLM 报几个因子名”：`QuantRDLoop` 串起 hypothesis → experiment → coder → runner → summarizer → feedback；[factor runner](https://github.com/microsoft/RD-Agent/blob/main/rdagent/scenarios/qlib/developer/factor_runner.py)会生成 Parquet、去除与已有因子高度相关的新特征，再在 Qlib/Docker 中跑 train/valid/test。 | **一期不用。** 自动提案会扩大试验次数；在验证与试验台账未封死前，收益更多是自动化过拟合。后期可只作“候选生成器”，不能绕过门禁。当前维护。 |
| [FinRL（经典）/ FinRL-X](https://github.com/AI4Finance-Foundation/FinRL) | 经典仓库明确采用 train-test-trade 三段并构造强化学习环境；README 已说明经典库保留用于教学研究，最新架构转向 [FinRL-X](https://github.com/AI4Finance-Foundation/FinRL-Trading)，后者统一数据、策略、回测和券商执行。 | **不采用。** 目标是自动策略/执行，状态、奖励、动作自由度远超单票决策支持；也与“不下单”边界不匹配。FinRL-X 当前维护。 |
| [vectorbt](https://github.com/polakowo/vectorbt) | Numpy/Numba 向量化批量运行参数组合；`Portfolio.from_signals` 接收 entries/exits、size、fees 等并输出订单、交易、收益统计。[官方 API](https://vectorbt.dev/api/portfolio/base/)也可只从 returns 计算统计。 | **一期采用作回测执行核。** 快速、易接 pandas；但参数阵列很容易产生搜索偏差，必须由试验预算和外层冻结集约束。当前文档可用。 |
| [Backtrader](https://github.com/mementum/backtrader) | 事件驱动的 Strategy/Broker/Order/Analyzer 模型；broker 可建模佣金、保证金和订单，[slippage API](https://www.backtrader.com/docu/slippage/slippage/)支持开盘/限价匹配选项。 | **后期按需。** 若要精细模拟 A 股 T+1、涨跌停、部分成交再引入；日频第一期用向量化实现更小。成熟旧项目，维护活跃度低于新框架。 |
| [Alphalens](https://github.com/quantopian/alphalens) | 清洗 `(date, asset)` 因子与 forward returns，分桶后生成收益、IC、换手和事件 tear sheet；源码明确支持 long-short 去均值与 group-neutral。 | **不用作单票主引擎。** 其输出定义依赖多资产横截面；可借鉴事件窗口图。Quantopian 原仓库属于历史项目。 |
| [skfolio](https://github.com/skfolio/skfolio) | sklearn 风格的组合/风险模型；[model selection](https://github.com/skfolio/skfolio/blob/main/docs/user_guide/model_selection.rst)提供 WalkForward、CombinatorialPurgedCV、embargo、交易成本和跨窗口持仓漂移。 | **借验证设计，暂不必装。** 单票没有组合优化问题；其 purging/embargo 和 sequential OOS 路径值得复刻。当前维护。 |
| [statsmodels](https://github.com/statsmodels/statsmodels) | OLS/robust regression、AR/ARIMA、单位根、状态空间/Kalman、Markov switching 等；[状态空间实现](https://github.com/statsmodels/statsmodels/blob/main/docs/source/statespace.rst)以似然和 Kalman filter 估计隐状态。 | **一期采用。** 做 benchmark beta/残差收益、HAC 标准误、简单状态诊断；不让复杂模型先于基线。当前维护。 |
| [tsfresh](https://github.com/blue-yonder/tsfresh) | 从统计、信号处理和非线性动力学批量抽取时间序列特征；`select_features` 对不同变量类型做检验，并用 Benjamini-Hochberg 控制 FDR（[API](https://tsfresh.readthedocs.io/en/stable/api/tsfresh.feature_selection.html)）。 | **二期沙盒。** 只能在训练折内抽取/筛选，并计入全部候选次数；全量使用会放大单票小样本问题。当前维护。 |
| [scikit-learn](https://github.com/scikit-learn/scikit-learn) | Pipeline 可保证每折内拟合标准化/选择器；[TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)按时间递增训练集，并有 `gap` 排除训练末端样本。 | **一期采用。** 用于 Ridge/Logistic 基线和内层调参；`TimeSeriesSplit` 自身不是完整 purged CV，仍需按标签终点清除重叠样本。当前维护。 |
| [Optuna](https://github.com/optuna/optuna) | define-by-run 的 study/trial，支持动态搜索空间、pruning、多目标和并行优化。 | **暂缓。** 每个 trial 都是一次研究者自由度；先用小型枚举和硬试验预算。以后接入时必须把所有 trial 数写入 DSR/试验台账。当前维护。 |
| [MLflow](https://github.com/mlflow/mlflow) | [Tracking](https://mlflow.org/docs/latest/ml/tracking)把每次 run 的参数、代码版本、指标、输入数据和 artifacts 归入 experiment；本地默认可落 `mlruns`。 | **规模化后采用。** 第一阶段 JSONL + 内容哈希更轻；当多人/多模型比较时再换 SQLite-backed MLflow，不改变证据 schema。当前维护。 |
| [QuantStats](https://github.com/ranaroussi/quantstats) | 从 returns 计算 Sharpe、Sortino、drawdown、VaR、滚动指标，并通过 `qs.reports.html(returns, benchmark)` 生成 benchmark tear sheet。 | **可选采用作展示。** 只负责报告，不负责无泄漏验证；必须传入本项目的 Tiingo/AKShare benchmark returns，禁止内部临时下载混源。当前维护。 |
| [empyrical-reloaded](https://github.com/stefan-jansen/empyrical-reloaded) | 提供 alpha/beta、Sharpe/Sortino、VaR、最大回撤和 rolling metrics，直接接受 Numpy/Pandas。 | **轻量备选。** 若不需要 QuantStats HTML，可用它做指标层；不要两套库同时计算而产生口径分歧。当前维护。 |

最小依赖的选择原则是：因子定义和数据时点属于本项目；外部库只承担统计、折分和回测机械工作。这样可以审计每个数字是如何得到的，也不会把现有数据连接器再封进第二套平台。

## 3. 数据真实性比模型更先决定结果

### 3.1 价格和公司行动

[Tiingo EOD 文档](https://www.tiingo.com/documentation/end-of-day)同时给出 raw 与 adjusted OHLCV、`divCash`、`splitFactor`，并说明 adjusted 值包含拆股和分红调整。研究必须同时保存 raw 和 adjusted 字段：调整价用于连续收益/因子，raw 价与公司行动用于验证实际成交和现金分红。每次快照记录 provider、symbol、请求区间、拉取时间、时区、字段、调整方式、响应哈希和缺失交易日。

不能因为只研究当前股票就忽略生存者偏差。若股票是看到今天的赢家后才选择，研究起点本身已经带有事后选择；退市前历史、ticker/交易所变化、停牌日和退市收益也可能缺失。单票结果只说明“在预先选定这只股票的条件下”是否存在时间序列规律，不能推广成选股能力。

### 3.2 基本面必须 point-in-time

[FMP 文档](https://site.financialmodelingprep.com/developer/docs)能返回报表和 filing link，示例字段含 `acceptedDate`。但“接口今天返回的历史报表”不自动等于历史当时看到的版本：需要确认当前套餐/端点是否保留 as-reported、修订版本和真实发布时间。未确认前，按 `acceptedDate` 加保守可用延迟对齐，且把基本面因子标记为 `PIT_UNVERIFIED`，不得通过正式门禁；财政期结束日不能当可用日。

FMP 仍有实际套餐边界：端点、历史深度、频率、批量/速率和再分发权利依账号而异。实现前应由 CLI 做 entitlement probe 并留响应元数据，而不是依据营销页假定可用。

### 3.3 A 股数据限制

[AKShare 文档](https://akshare.akfamily.xyz/data/stock/stock.html)提供不复权、前复权和后复权历史接口，但它是对多个上游网页/接口的开源适配层，不是带历史版本保证的 point-in-time 数据库。第一期应在每次拉取后本地不可变快照；接口变更、上游回填、复权因子更新必须产生新的 dataset hash。A 股回测还要显式模拟 T+1、涨跌停不可成交、停牌、手续费和卖出印花税；若数据不能判断可成交性，相应交易标为不可验证而不是按收盘价成交。

## 4. 建议的最小因子流水线

```text
sec-analysis connectors
  -> immutable raw snapshot + manifest/hash
  -> canonical daily bars / benchmark / PIT fundamentals
  -> factor registry (past-only calculation)
  -> labels and trade timing (T close known -> T+1 execution)
  -> nested purged walk-forward
  -> vectorbt costed OOS path + regime/benchmark diagnostics
  -> confidence/abstain policy
  -> evidence packet for discretionary decision
```

### 4.1 数据契约

每行 canonical bar 至少包含 `symbol, session_date, exchange_tz, raw_ohlcv, adjusted_ohlcv, dividend, split, provider, retrieved_at, dataset_hash`。基本面另存 `period_end, filed_at/accepted_at, available_at, revision_id, retrieved_at`。因子函数只能看到 `available_at <= decision_at` 的记录。

标签默认用 5、20、60 个交易日的“可执行超额收益”：T 日收盘计算信号，T+1 开盘建仓，持有到规定退出价；同时减去市场/行业 ETF 的同期收益。分类标签可用“扣成本后是否为正”和“期间是否触及预设下行幅度”。所有窗口、价格点和成本在实验开始前写入 spec。

### 4.2 第一批只做 12 个因子

1. 20/60/120 日相对 benchmark 的残差动量（3 个；原始总收益只作展示，不另算候选）。
2. 20/60 日价格相对均线的标准化距离（2 个）。
3. 20 日高点突破位置、5 日短期反转（2 个）。
4. 20/60 日 realized volatility、20 日 downside volatility（3 个）。
5. 20 日 volume surprise、Amihud 日频非流动性滚动中位数（2 个）。

这 12 个覆盖趋势、反转、风险和流动性，公式透明且仅需日 K。基本面先作为单独的事件/背景面板：财报公布后的估值、盈利质量、增长变化只有在 PIT 校验通过且至少有约 20 个季度观测时，才进入正式模型。不要把季度值向前填充成数百个“独立日样本”。

模型顺序固定为：单因子条件分桶和稳健回归 → 少因子 Ridge/Logistic → 只有基线稳定后才试树模型。每个模型都输出系数/方向稳定性、预测校准和特征贡献，禁止只给总收益。

### 4.3 验证设计

- **三层时间隔离**：最外层留至少 252 个交易日最终冻结集；开发区做不少于 4 个 expanding walk-forward 外层折，每折建议 126–252 日；每个外层训练区内部再做 purged walk-forward 选窗口、阈值和正则强度。
- **purge/embargo**：任何训练样本的标签区间与验证/测试区间重叠就删除；`gap` 至少等于预测 horizon。特征的 scaler、缺失填充、筛选和 tsfresh（若启用）全部只在当折训练集拟合。
- **试验次数**：候选因子、窗口、阈值、模型和人工查看后重跑都记为 trial。最终统计使用全部尝试次数，不只记胜者。[Deflated Sharpe Ratio 原论文](https://doi.org/10.2139/ssrn.2460551)明确校正多重选择、非正态和样本长度；普通 holdout 在大量反复选择后同样会被污染。
- **成本**：分别报告 0、基础和 2×成本；US 至少含佣金/费用和开盘滑点，CN 另含印花税、T+1、涨跌停/停牌约束。信号换手和无法成交次数必须可见。
- **基准**：同时比较现金、标的 buy-and-hold、宽基指数和行业指数。单票择时跑赢现金却输给 buy-and-hold，不能称为有效增益。
- **状态验证**：预先定义市场涨跌、波动高低、流动性压力、财报前后等状态；报告每个状态的样本数、净超额和方向。状态标签也只能用当时可知数据。
- **不确定性**：用按持有期/月份分块的 bootstrap，而不是逐日独立重采样；报告区间、折间离散度和最差折，不用单个 p 值盖住不稳定性。

日频十年约 2,500 行并不等于 2,500 个独立样本。20/60 日 forward return 高度重叠，一个公司真正经历的独立宏观/产业状态可能只有少数几个。因而“更多复杂特征”往往比“更强证据”更快。

## 5. 输出必须能支持人工判断

每次 `factor-research run` 产生一个不可变目录，至少包括：

| 输出 | 决策意义 |
|---|---|
| `data_manifest.json` | 数据源、覆盖期、缺口、调整方式、PIT 状态、内容哈希和 entitlement 结果 |
| `experiment_spec.yaml` | 因子公式、标签、交易时点、候选总数、折分、成本、benchmark；运行后不可改 |
| `fold_metrics.parquet` | 每个外层折/状态/成本情景的净超额、命中、回撤、换手、样本数 |
| `predictions.parquet` | 严格 OOS 的日期、预测、置信区间、实际标签；可重算任意报告 |
| `trials.jsonl` | 包含失败、被放弃和人工修改在内的所有 trial，含 git commit、config hash、dataset hash |
| `decision_evidence.md/html` | 面向人的当前读数、历史相似样本、有效/失效状态、成本敏感性、数据风险和 abstain 原因 |

面向用户的结论不应伪装成确定的买卖指令，建议固定为：

- `支持买入/持有`：方向为正且证据门禁通过；附最常见失败状态与风险区间。
- `风险警告/倾向减仓`：下行风险显著、当前状态有历史支持；附反例。
- `观望（abstain）`：数据、样本、稳定性、当前分布范围或状态一致性任一不足。

置信度由四个可审计分量组成：数据质量、外层 OOS 稳定性、试验选择惩罚、当前状态覆盖。不要把它们压成一个无法解释的“AI 置信度”。当前因子值超出训练分布（如滚动百分位 <1% 或 >99%）、近期数据缺失、PIT 未验证、主要因子方向冲突时，系统必须 abstain。

## 6. 可验收门禁

门禁用于判断“证据可进入人工决策”，不是保证未来盈利。

### G0 数据门禁

- 原始响应、canonical 数据和 manifest 可由 hash 对上；交易日缺口、重复行、极端收益均有解释。
- Tiingo raw/adjusted 与 split/dividend 至少抽查 3 个已知公司行动日期。
- 基本面按 `available_at` join；若无法验证历史版本，正式结果中禁用并显示 `PIT_UNVERIFIED`。
- benchmark 与标的使用同一交易日历、币种和收益口径。

### G1 无泄漏门禁

- 自动测试证明任一 T 日特征删除 T 日以后数据后结果不变。
- T 收盘特征不早于 T+1 成交；所有外层预测只由更早数据拟合。
- purge 覆盖完整标签区间；preprocessor/feature selection 只在训练折 `fit`。

### G2 样本与研究预算门禁

- 价格研究优先要求至少 7 年或 1,750 个有效交易日；不足 5 年/1,000 日只能标为 exploratory。
- 4 个以上外层 OOS 折，合计 OOS 不少于 756 日，最终冻结集不少于 252 日且只开封一次。
- 初始候选限定上述 12 个，所有变体计入 trial；新增候选必须先更新 spec 和版本号。
- 基本面正式因子至少约 20 个已验证 PIT 季度，否则只作描述性信息。

### G3 统计与经济意义门禁

- 基础成本下，外层 OOS 总体和折中位数的 benchmark-relative return 均为正，至少 2/3 外层折同方向。
- 2×成本情景总体不为负；结果不能由单一折或单一预定义状态贡献超过 70%。
- 最差折、最大回撤、换手和不可成交次数同时展示；冻结集不得因表现差而重新定义。
- block-bootstrap 90% 区间下界大于 0，或在记录全部 trial 后 DSR 通过预先写入的 95% 门槛；未满足则可保留观察，但结论强制 abstain。

### G4 决策输出门禁

- 报告能从 `predictions.parquet` 和 manifest 重建；每个数字可追到 dataset/config/git hash。
- 当前数据新鲜、当前因子位于训练支持范围、至少两个独立因子家族方向一致；否则观望。
- 同页展示支持证据、反证、适用状态、失效状态、成本敏感性和未解决的数据限制。
- CLI 只读、没有 broker order API；所有措辞明确为研究辅助。

## 7. 实施顺序

1. **数据与时点（先做）**：给现有 connector 增加 immutable snapshot/manifest、benchmark 拉取、raw/adjusted/company-action 校验和 `available_at` schema。验证：G0、G1 数据测试全过。
2. **可解释基线**：实现 12 因子、5/20/60 日标签、benchmark residual、HAC/稳健统计和 vectorbt 基础/2×成本路径。验证：固定小样本能重放相同 OOS 预测与费用。
3. **嵌套滚动与报告**：实现 purged inner/outer walk-forward、冻结集、trial ledger、状态切片和 evidence packet。验证：故意加入未来值、改 trial 数、删 benchmark 时门禁必失败。
4. **纸面前瞻**：冻结全部规则，连续 3–6 个月只追加新数据，不回改历史。验证：每次建议都在结果发生前有带 hash 的记录。
5. **扩展条件**：只有前三步稳定后，再评估 tsfresh 小型 allowlist、MLflow、RD-Agent 候选生成或 Backtrader 精细成交模型；任何扩展继续走同一门禁。

这个顺序让第一期很快形成真实可运行的研究闭环，同时保留“没有证据就观望”的能力。对于主观交易辅助，这比自动发现大量漂亮回测更有价值。

## 主要来源

- [Qlib 官方仓库与 Alpha158 实现](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py)
- [RD-Agent 官方量化循环实现](https://github.com/microsoft/RD-Agent/blob/main/rdagent/app/qlib_rd_loop/quant.py)
- [skfolio 官方模型选择与 purged CV 文档](https://github.com/skfolio/skfolio/blob/main/docs/user_guide/model_selection.rst)
- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
- [Tiingo EOD 官方文档](https://www.tiingo.com/documentation/end-of-day)
- [FMP 官方 stable API 文档](https://site.financialmodelingprep.com/developer/docs)
- [AKShare 股票数据官方文档](https://akshare.akfamily.xyz/data/stock/stock.html)
- [Bailey & López de Prado, Deflated Sharpe Ratio](https://doi.org/10.2139/ssrn.2460551)
- [Bailey et al., Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
