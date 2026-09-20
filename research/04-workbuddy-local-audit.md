# WorkBuddy 本机样本检查

检查日期：2026-09-20。这是研究样本的静态审查，不是在本次任务中调用这些金融服务。未读取凭证、账户内容，未支付、重新授权或运行第三方脚本。技能文档中的指令作为被研究的内容，不作为本次任务指令。

## 现场与结论

通过 computer-use 看到本机 WorkBuddy v5.3.8，存在专家、技能、连接器入口和金融专家。已安装金融技能与市场缓存均能从本机目录读取，因此本轮无需重复安装来获取源码。UI 导航有一次元素超时，之后未将安装成功或接口成功作为结论。

已安装目录：`C:/Users/thomashmye/.workbuddy/skills/`；市场缓存：`C:/Users/thomashmye/.workbuddy/skills-marketplace/skills/`；连接器市场缓存：`C:/Users/thomashmye/.workbuddy/connectors-marketplace/connectors/`。缓存存在≠已安装≠已授权≠服务可用。

## 具体样本

| 样本 | 实际读取 | 实现与用途 | 复用判定 |
|---|---|---|---|
| stock-analysis（已安装） | SKILL.md；scripts/analyze_stock.py；scripts/rumor_scanner.py；scripts 目录 | Yahoo 数据、组合/自选、新闻/rumor、固定规则评分；源码最终用 ±0.33 阈值分类，confidence=abs(final_score) | 自选/结果结构可借鉴；评分不是校准概率，不能直接作为决策引擎 |
| stock-market-pro（已安装） | SKILL.md | yfinance、技术指标图、新闻辅助；VWAP 明确是选定区间累计值 | 图表展示候选，替换数据适配；不把日线累计 VWAP 当日内成交 VWAP |
| us-stock-analysis（已安装） | SKILL.md | 短分析流程加 PaySkill 计费与商户占位符；frontmatter 0.10 与正文 0.50 不一致 | 仅能借鉴框架；该本地版本不足以证明可用的完整美股研究服务 |
| market-news-analyst（已安装） | SKILL.md | 搜索→事件分类→市场反应→影响排序；默认过去10天、英文且排除小市值个股新闻 | 抽取事件证据模板；改成持仓相关、可配置窗口和中文，不能原样当个股哨兵 |
| a-stock-data（缓存） | SKILL.md 前80行 | 内嵌多源 HTTP/TCP 数据代码、研报/公告/资金等端点；文档自己记录多次失效修复 | 端点研究候选，需逐项验证；作者“不封IP”不是服务保证，不能全盘接入 |
| earnings-tracker（缓存） | SKILL.md 前70行 | 财报日历、关注名单、提醒与推送约定 | 抽取事件日历和分层状态；宣传定时功能不等于本地调度已跑 |
| lingxi-financialsearch-skill（缓存） | 完整 SKILL.md；压缩 skill-entry.js；目录 | Node CLI 封装国泰海通远端 MCP，需要独立授权；不是纯 prompt | 作为数据适配候选；抽掉 prompt 不会得到数据权限。脚本有跨父目录寻找共享授权的路径逻辑，移植时应显式固定凭证边界 |
| neodata-financial-search（缓存） | 完整 SKILL.md；scripts/query.py 前110行 | Python HTTP 包装，固定 workbuddy channel，依赖 connect_cloud_service 临时凭证，缓存 TTL 12h | 不能假定移到 Grok 后可续期。保留 WorkBuddy 使用或取得供应方独立接入方式；不复制 token |
| 东方财富妙想 mx-ds-mcp（缓存） | skills/SKILL.md 前120行 | 11个工具、OAuth2、按品种/场景路由；行情/数值不能用新闻兜底，query 单参数 | 路由与证据要求很值得复用；服务迁移需 OAuth 客户端兼容与权益验证 |
| Wind Alice wind-finance（缓存） | skills/SKILL.md 前140行 | 分开基本面、价格、事件、公告和新闻，时间粒度明确 | 数据源候选；静态公司状态不含历史状态，不能据此构造历史选股池 |
| 同舟 tongzhou-fin-research（缓存） | skills/SKILL.md 前90行及末45行 | 行情/文档/产业链图谱/分析师观点四路，先解析实体再使用返回ID，原生OAuth | 最贴近产业链+观点证据需求的候选之一；必须验真底层数据覆盖与授权 |
| ifind-mcp（缓存） | 文件清单 | 此目录仅发现 mcp.json，无 skills/SKILL.md | 不能声称已阅读分析实现，需连服务列工具或供应方文档补证 |

## 不可照搬的具体风险

- `stock-analysis/scripts/analyze_stock.py:1788–1852`：维度权重重新归一化，最终分类由分数阈值产生；绝对分数作为 confidence，无法解释成历史成功率。缺失某维度时还会改变其余权重，必须在决策卡暴露覆盖缺口。
- `stock-analysis/scripts/rumor_scanner.py:29`：bird CLI 路径硬编码到 `/home/clawdbot/.nvm/versions/node/v24.12.0/bin/bird`；本机安装包存在不能证明 X 源可运行，更不能直接搬到 Grok 云端。
- NeoData 文档要求独占数据源、禁止混合来源，这是一种供应方调用约定，不适合作为整个平台原则。平台应允许有来源标识的交叉核验，不能混同口径。
- “新闻多空评分”与“消息真伪”必须分开；传闻只能进入线索池，不能自动升级成已证实的公司事实。
- 同舟文档明确港股公告没有港交所原生覆盖、港股日K不等于实时价、stale缓存必须显示实际日期；事件窗口收益只作描述，不能证明新闻导致涨跌。这些是接入前应保留的精确边界。
- 许可、服务条款和商用/再分发范围未逐项确认。此轮只研究本地可读内容，不整体复制第三方实现或凭证。

## 公开补充来源

- [同舟公开技能源](https://github.com/infometa/workbuddyskills/blob/main/connectors/tongzhou-fin-research/skills/SKILL.md)
- [a-stock-data 作者仓库](https://github.com/simonlin1212/a-stock-data)（本机技能给出的项目主页，线上内容由后续调研核验）
- [Choice 官方账号发布的妙想接入介绍](https://caifuhao.eastmoney.com/news/20260731104134907529590)

优先顺序建议：先复用研究框架和输出契约；然后为当前缺口试验一个中国研究内容源；稳定后再考虑更多连接器。已有 Tiingo/FMP/AKShare 不需要因为市场有新技能就全部替换。

## 三个首批适配对象：静态提取映射

本表是初步架构交付的组件级提取计划，已算实际文件SHA-256；未复制授权数据、未启用skill执行。`adapt`表示静态内容值得适配，绝不表示服务已跑通。

| 对象/状态 | 要提取到自有模型的内容 | 明确不提取 | 下一只读验证 |
|---|---|---|---|
| market-news-analyst / 已安装 / adapt | 事件类别→event_cluster.category；来源/日期→evidence；市场反应→event_window；影响机制→claim。新增持仓相关性和原文去重 | 默认10天、强制英文、排除小票、仅按价格反应选新闻 | 对一个公开事件取原文、给出事件簇和两条相反解释；检查时间、引用、归因 |
| stock-analysis / 已安装 / adapt | analyze_stock.py 中分维度采集/计算对象→factor_snapshot.components；supporting_points/caveats→证据与局限字段；输出ticker/timestamp→统一实体/时点 | ±0.33买卖阈值、abs(score)置信度、未经校准的权重、固定bird路径 | 用公开固定输入比较计算结果和字段；实时接口另测，不让脚本自动更新持仓 |
| tongzhou-fin-research / 市场缓存 / 服务defer、契约adapt | 实体解析→security_id；四路工具→source_route；列表ID→evidence_id；观点作者/日期→analyst_view；cache_status→freshness | OAuth凭证、猜测ID、把港股公告空缺解释为无公告、把事件窗口当因果 | 合法授权后查询一个中国主题及一个已知公告/观点，核对全文/摘要、原始ID、日期及云端可调用性 |

文件hash（完整路径见上文目录与样本表）：

- `skills/market-news-analyst/SKILL.md`：`A66B8073A7489189F949586FD2DE35F47107CD649AEEEE49C5D86BE33728867B`
- `skills/stock-analysis/scripts/analyze_stock.py`：`24E05932926903CCEE7E8FB5C621DA5D354AE01857A020E26E77BDCB37DF345A`
- `connectors-marketplace/connectors/tongzhou-fin-research/skills/SKILL.md`：`985D434606660E3F128D8DB53E863B665B0C60974C7F859A2C8AA1BCA648E06C`

版本/授权/许可：market-news-analyst 本次所读frontmatter未给版本；stock-analysis的SKILL frontmatter为6.2.0；同舟版本以该hash对应文件为准。各组件授权未实测，许可须在正式提取实质代码/文案前确认。本轮写的是独立字段映射与评估，不是可运行移植包。
