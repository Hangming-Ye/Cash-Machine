# 数据与研究产物模型

以下为拟定的逻辑记录（P-02、P-04、P-07、P-08），不要求逐实体建表。使用 JSON 存结构、CSV 存数值表、Markdown 存人读摘要，原始文档原样保存。文件之间用 ID／相对路径关联，无外部数据库。

## 通用约定

- 文本字段用 UTF-8。日期时间包含时区，内部比较转 UTC，市场交易日单独保存；未知时间为 null 并说明，不用 epoch／抓取时间替代。
- 证券身份含 market、exchange（可得时）、symbol、currency；跨市场同名／同代码先消歧。数量、单位、币种和字段口径随值保留，缺失不补零。
- 引用指向私有工作区中的相对路径、记录 ID 和原来源定位；不允许路径逃逸。公开输出按用途排除非公开账户信息。
- 运行 ID 由程序生成，不以当天日期作为唯一 ID。取数原文、计算、交付与复盘各自产生新记录，不覆盖历史事实。
- summary／lesson 的更新保存旧版，当前文件可替换。版本用于防止同时覆盖及追溯，不是任务状态机。

## 逻辑实体

| 实体 | 必要字段／关系 | 校验与生命周期 |
| --- | --- | --- |
| ResearchRequest | request_id、question、scope、horizon、as_of、method_tags、input_refs | 范围来自用户调用；标签可组合，不是固定流程枚举。as_of 是研究知识截止点，非默认数据时间 |
| WorkRecord | record_id、request_id、created_at、owner、input_refs、output_refs、outcome、limitations | 每次执行生成；outcome 为 complete／limited／failed，研究结论另列，避免“无机会”混同于失败 |
| SourceResult | source、operation、security_or_topic、observed_at、retrieved_at、available_at、coverage、payload_ref、quality、errors | observed_at 是事实时点，available_at 是能获知时点；缺失需声明。来源适用性看字段与权限，不看工具是否返回 200 |
| Evidence | evidence_id、source_ref、locator、published_at、retrieved_at、available_at、content_kind、claim、scope、units、limitations、unknown_reasons | content_kind 区分披露事实、第三方观点、研究假设与计算结果；观点转述不变成事实；published_at／available_at 未知时分别说明原因 |
| PortfolioSnapshot | snapshot_id、broker、reported_at、retrieved_at、accounts、positions、coverage、complete_read、confirmed_empty、unknown_reasons | 多账户／币种保留原值；每条 position 以 account_ref 关联本快照中的账户；空仓仅在读取完整且明确空结果时成立；Flex 标 T+1；失败不可产生假快照 |
| DataGap | gap_id、request_id、required_content、attempts、impact、next_action | attempts 含源／路径、时间、结果；G-01 等目录 ID 可关联多次尝试，无状态迁移要求 |
| Calculation | calculation_id、kind、input_refs、parameters、assumptions、engine_version、result_ref、warnings | 输入冻结与版本可回查，重复执行数值精度在协议中声明；数值合法不等于假设成立 |
| FactorExperiment | experiment_id、request_ref、request_hash、hypothesis、failure_regimes、expression、parameter_sets、dataset_ref、available_time_rule、target、horizon、bar_interval、baseline、split、primary_metric、metrics、costs、trial_group、result_ref | request_ref 指向完整不可变实验请求，request_hash 校验其内容；展示字段须与请求一致，primary_metric 是预先选定指标，metrics 是实际输出；先记录方案后执行，记录全部组合与参数试验；探索／验证／最终留出分离；禁止最终留出反馈继续参与调参 |
| Decision | decision_id、security_or_topic、as_of、label、reason_refs、price_or_conditions、price_or_conditions_reason、evidence_limited、limitations、horizon、risks、invalidators、previous_id、memory_packet_refs | 标的评价 buy／sell／watch；无机会／无增量等结论适用于相应研究。watch 可标 evidence_limited，价格无法支持则 null 并说明原因 |
| Review | review_id、decision_id、decision_as_of、review_at、observed_outcome、process_findings、counterevidence、lesson_refs | decision_as_of 固定原判断知识截止点；先确认是否到期／触发，未到不判输赢；区分资料、推理、执行与市场路径，后验事实不覆盖旧依据 |
| TopicSummary | topic_id、version、known_at、updated_at、current_thesis、support_refs、opposing_refs、changes、open_questions、next_checks；可选 topics／methods／securities／aliases | 长期工作摘要可更新；旧假设被替代须有依据；未解决的矛盾保留。检索元数据随版本保存且只辅助相关性，不产生新事实或倒填历史。可含多个标的和市场 |
| Lesson | lesson_id、version、check_or_method、applies_when、source_refs、counterexamples、validity、review_condition、known_at、updated_at；可选 topics／methods／securities／aliases／duplicate_of | 有出处、条件和局限；validity 区分 candidate／usable／superseded，不代表统计认证或人工审批阶段。duplicate_of 是版本化检索提示，不自动合并／删除；自指、悬空或循环关系不得静默排除。新反证可使其不再按有效经验使用 |
| MemoryPacket | packet_id、request_id、query、context_mode、as_of、decision_id、review_at、selected_refs、exclusions、budget、content_ref | decision_id／review_at 仅 review 模式必填；selected_refs 指向具体版本，review 输出区分当时输入与后续事实；记录实际交给 Bot 的材料；预算仅约束该材料，不保证原生总上下文。无命中与检索失败明确区分 |

T033 实现中，`Calculation.input_refs` 使用本次记录内复制的输入 bytes，或使用已由源 manifest 校验的不可变引用；manifest 同时保留原引用、冻结引用、文件哈希及源 manifest 哈希。`parameters` 保存完整请求，`result_ref` 指向同目录结果，`calc_<record hex>` 可解析到 typed Calculation。该记录保证复算输入可定位，不证明研究假设成立。

## 目录与关联

```text
/workspace/cash-machine/
  app/                     # 程序及依赖描述，可重建
  config/                  # 无密钥设置，秘密引用而非秘密值
  data/
    requests/<request_id>.json
    records/<record_id>/    # 来源、证据、计算及交付
    topics/<topic_id>/      # current + previous versions
    lessons/<lesson_id>/    # current + previous versions
    memory-packets/<packet_id>/
    gaps/                  # 每次缺口记录
```

目录名是 P-02 默认，可改变根路径；记忆索引从 topic／lesson 的已验证字段构建，可重建，不是新的事实权威。所有数据写入遵循私有工作区权限，凭证不放 data 目录。

## 更新与冲突

原始证据／实验／判断追加，修正另存并指向旧记录。摘要和经验由该主题负责 Bot 提议更新，小工具校验字段、引用存在性和 expected_version 后保存；同次写入的版本比较与替换须串行完成。冲突返回已有版本，调用者回读后合并重提；不自动选“最后一个写入者胜出”。不要求跨多文件事务，单个产物完整后才由索引引用。

记忆模型提出“合并／替代”不等于程序知道其语义正确。结构检查只验证字段与引用，反证是否被保留、压缩是否改变意思由样例和研究复核检查。个人清理删除有明确用户授权时执行；本轮工具不增加通用批量删除入口。

## 归档与历史时点的统一规则

Decision／WorkRecord／Review 由 Bot 生成草稿，通过 `check artifact --archive` 校验并固化正文／附件，取得记录 ID 后再用于复盘和经验引用；不以可变草稿充当历史记录。命令默认只校验，详见 [CLI 契约](contracts/cli.md)。

主题／经验每个版本的 known_at 是程序记录的该版本形成时间，不能按被引用材料的发布日期回填。updated_at 只供展示最后更新，不能代替版本的 known_at。historical 模式按截止点选旧版本及当时的 validity；当前版本后来停用，不改变旧判断当时收到什么。review 模式保持原判断与后续事实两区隔离，缺原输入或历史版本就显式受限。

FactorExperiment.request_ref 的完整请求是复算依据，包含计算契约列出的全部必需字段；摘要字段或参数集与其不一致时拒绝执行／复算，不以默认参数补齐。冻结请求与结果文件均保留；失败或未执行时 result_ref 可为空并明确原因。
