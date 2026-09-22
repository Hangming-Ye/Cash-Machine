# 按需 CLI 契约（拟实现）

命令名 `cash-research`；所有命令均为计划接口，本轮不存在可执行产品程序。使用请求文件传结构化输入，避免 Bot 拼接长命令或把秘密放在命令行。全局可选 `--root PATH`、`--config PATH`、`--env-file PATH`；配置仅引用秘密，输出不得回显秘密值。

## 公共结果

成功输出 JSON：`schema_version, request_id, operation, status, artifacts, warnings, gaps, error`。status 为 ok／partial／error，是一次调用结果，不是任务状态机。artifacts 只含路径、类型、内容摘要与 ID，完整数据落盘。

退出码：0=命令完成（ok 或 partial，调用者必须读 status）；2=输入／数据质量／版本冲突，调整输入后重跑；3=外部来源或运行错误。因子无增量是正常计算结果，不是错误。错误详情标明 unauthorized、unsupported、rate_limited、empty、stale、conflict 等原因；不得将账户失败作为 ok 空仓。

## 命令表

| 命令 | 请求 | 输出及边界 |
| --- | --- | --- |
| `data fetch --request FILE` | 现有 source、operation、对象、日期范围／as_of、所需字段 | SourceResult、原始响应的必要部分及规范化数据；不调用订单写接口，不自行启用新源 |
| `data ingest --request FILE` | Bot 已取得的文件／URL 定位、发布时间、获取时间、类型、口径与限制 | Evidence 及引用 ID；可导入带来源的完整数值序列或文本材料；数值须校验字段／时点／覆盖，文本仅做资料归档和元数据检查，不声称验证了原文语义 |
| `compute factor --request FILE` | calculations.md 的因子／实验请求 | 冻结请求、试验记录、结果表、数据质量／验证警告；禁止任意代码执行 |
| `compute valuation --request FILE` | method、来源和情景假设 | 估值与敏感性表、计算依据和警告；不会自动写 buy／sell |
| `memory recall --request FILE` | 当前问题、证券／主题／方法、context_mode、as_of、材料预算；review 模式另含 decision_id、review_at | MemoryPacket、版本及选中／排除依据；无命中与检索失败分开；当前／历史／复盘规则见下文 |
| `memory apply --proposal FILE` | Bot 提出的主题／经验更新、source_refs、expected_version | 新版本及旧版引用，或字段／引用／冲突错误；不覆盖原始证据，无自动删除原始记录 |
| `check artifact --request FILE [--archive]` | 草稿路径、record_type（Decision／WorkRecord／Review）、引用列表；更正关联旧记录 ID | 默认只检查；显式 --archive 在检查通过后保存新不可变记录并返回 ID／路径；若草稿含 `run_manifest_ref`，则加载该工作区相对 JSON，在 manifest 不完整、乱序或缺 required 阶段时拒绝；不承诺判断自然语言真实性，也不判断经济真伪 |
| `check run --request FILE` | FILE 即为 run manifest（`data/runs/<request_id>/manifest.json`） | 打印 JSON：`status`、`next_stage_id`、`missing`；manifest 无效退出码 2；文件可读即使仍有未完成阶段也退出 0，由调用方按 `next_stage_id` 继续；不归档、不启动循环；不判断经济真伪 |

T033 的本地实现已将两类券商只读 operation 接入 `data fetch`，只在适配器返回通过共享模型校验的账户关联与覆盖时发布 `PortfolioSnapshot`；partial snapshot 保留 `complete_read=false`，失败不生成快照，完整且明确空读取才可 `confirmed_empty=true`。这只证明 MockTransport／fake SDK 集成，不证明 live 权限。

`compute valuation` 调用纯计算引擎后，在一个原子记录目录中保存完整 request、result、Calculation 和 manifest。普通输入复制为冻结 bytes；已有 hash manifest 的不可变输入保留引用并记录其 manifest hash。`calc_<id>` 可解析到 typed Calculation，result 不生成 Decision label。输入／单位／方法校验错误为退出码 2，发布运行错误为脱敏退出码 3。

## 判断与复盘归档入口

Bot 将 Decision／WorkRecord／Review 草稿及报告写到任务自己的暂存目录，随后显式调用 `check artifact --request FILE --archive`。基础请求保留 `draft_ref`、`record_type`、`reference_refs`；需固化报告时另传 `report_ref`、`attachment_refs`，修正已有 Decision 时由草稿的 `previous_id` 指向旧记录并可传 `change_explanation`。程序校验相应模型、引用、路径和秘密字段；草稿可选的 `run_manifest_ref` 是唯一触发 run 完整性检查的字段——省略该字段的草稿仍可通过；设置后若 manifest 不完整则拒绝（不得把缺阶段当成成功的 limited 归档）。通过后生成记录 ID，将正文及需固化附件保存到 `data/records/<record_id>/`，返回 canonical record、report body、各 attachment 与 hash manifest 的类型化 ID／路径。manifest 保存源文件和归档文件哈希、memory packet 关联，以及相对旧 Decision 的结构化字段差异；差异只说明字段值改变，不宣称程序理解金融原因。引用已归档证据时不重复复制；不得只指向仍可被改写的草稿来代表历史报告。

`check run --request FILE` 的 FILE 是研究 run manifest 本身。它只报告下一阶段，不归档，也不启动调度或轮询。

不带 `--archive` 不写正式记录；校验失败不形成已归档记录。更正生成新 ID，保留 previous_id／被更正引用，不覆盖旧文件。Bot 不直接改正式历史记录。memory apply 只更新摘要与经验，不能替代判断归档。这里复用原命令组，未增加服务或审批流程。

## 数据读取操作白名单

- 通用：quote、bars（含 bar_interval，daily_bars 可作为日频别名）、news、profile、statements，仅路由到 [data-sources.md](../data-sources.md) 已有对应来源；是否支持以实际适配器／权限为准。
- 券商：accounts、positions、executions。watchlist 仅在现有云端能力核验后启用；不能为了满足命令名假返回列表。
- 请求超出当前权限或字段：返回明确缺口；Bot 可用现有工具／网页继续补证，不自动安装供应商插件。

## 记忆检索和更新（P-07、P-08）

请求显式选择 context_mode，不由模型猜测使用哪个时点：

检索请求可继续传显式 `topic_ids`／`lesson_ids`；两者均为空时按 query 检索文件索引。可选 `query_metadata` 只接受 `topics`、`methods`、`securities` 三个非空字符串列表；证券使用调用方已有的规范市场／交易所／代码身份字符串。程序先按截止时点选择记录版本并校验来源可得时间，再使用该版本的 topics／methods／securities／aliases 和正文作轻量词项匹配。显式 ID 保持原有精确读取语义，不被相关性或去重过滤。

Lesson 的可选 `duplicate_of` 只在查询检索中、同一截止点的声明版本与其未再指向其它重复项的目标同时被选中时排除重复项；自指、悬空或循环关系保留记录并报告原因，不静默丢失。该字段不合并内容，也不代替来源、适用条件、反例或 T052 的语义整理。

- `current`：as_of 为本次研究截止点；按主题／证券／方法选择截至该时点可用的摘要和经验。
- `historical`：as_of 为要还原的历史截止点；只选 known_at ≤ as_of 的版本，每条取当时最新版本并按该版本的有效性处理，同时检查支持材料的 available_at。不得拿当前版本的内容或后来失效标记倒写过去。
- `review`：decision_id 指向原判断，as_of 与原判断截止点一致，review_at 为本次复盘截止点；输出两个明确分区。原判断区读取当时固化的输入／记忆引用，后续事实与经验区仅取截至 review_at 的材料，禁止把后一区混入“当时已知”。

TopicSummary／Lesson 的 known_at 由程序在版本保存时记录且不可回填为原材料发布日期。后来用旧材料整理的经验仍是后来才形成；历史版本缺失时返回明确缺口，不用当前摘要重建后宣称是当时记忆。回查原判断优先使用其固化 memory_packet_refs，无法定位则标受限。

索引允许别名和关联主题，避免只按证券代码匹配。先按模式筛时间和版本，再做相关性筛选；材料事实时间、公开可得时间与经验形成时间分别处理。

缺少语义向量检索不是允许忽略跨公司教训的理由：小样例必须包含换措辞和跨标的的同类问题。若轻量词项／主题索引漏召回，再报告具体缺口和 Mem0 等候选成本，而非无证据扩大基础设施。

材料预算在请求／配置显式给出；摘要不足以容纳来源、反证及适用条件时，返回精简索引与按需阅读路径，不机械截断关键语义。报告截断／遗漏情况；只限制返回材料，不保证原生总上下文。

apply 的字段校验包括来源可定位、版本、时间及必要条件／局限；模型提炼是否正确仍靠证据复核。主题负责 Bot 可以完成更新，不增加每条经验都要用户批准的工作流。候选经验作为提示使用，不能仅靠 validity 字段宣布已统计验证。

## 部署与秘密

运行于 Grok 共享云电脑的私有项目目录，Windows 上可进行离线开发检查。部署时显式接现有受保护凭证来源；不把本机密钥打包，也不把实际 .env 内容写进任务或文档。任意原始响应入库前按用途排除 token／秘密；账户数据保留在私有目录，不上传到公共模板。

云电脑手装依赖不视为永久存在；程序和锁文件可重建，运行数据放共享持久目录。依赖缺失明确报错，使用安装说明恢复，不新增后台自愈进程。
