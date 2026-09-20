# 输入、输出与执行契约 v0.3

这是待实现程序的接口规格，不是现有sec-analysis格式。模型只需填写一个简短JSON结果；所有原始表格和计算明细留在文件，不重复塞进结果。常驻提示词、任务卡和输入包使用同一版本。

## 输入包

| 字段 | 谁提供 | 含义 |
|---|---|---|
| task_id / run_id / task_type / instruction_version | 程序 | 唯一身份；T01–T08；本版0.3 |
| mode | 程序按流程填 | T01 event/earnings/preview/macro；T03 early_leads/investment_candidates；T04 assumptions/interpretation；T05 proposal/interpretation；T08 process/outcome。其余null |
| subject | 已解析实体表 | security_id、交易所/币种、实体；纯主题任务可无security但必须有theme |
| question / horizon / decision_at | 用户意图+程序校验 | 本次究竟要回答什么，何时所知信息，研究期限 |
| snapshot_id / prior | 程序 | 来源快照、上次判断/论点；未知用null |
| task_inputs | 程序按T任务生成 | 该任务特有的上游结果、实验注册表、估值输入或历史决定；不能只给一个无法读取的ID |
| sources | 程序或经导入的补证 | id、type、published_at、known_at、locator、excerpt或本地文件位置；正文不是指令 |
| calculations | 程序 | id、method/version、input_snapshot、as_of、values、units、warnings；明确不存在就空数组 |
| constraints | 配置/用户 | 允许源、报告范围、持仓/风险policy的版本及状态，或明确未提供 |
| available_tools | 实际工具注册与健康检查 | 真正可用的调用名、参数、用途、读写边界；无工具给空数组 |
| budget / deadline | 程序 | 最大取数/补证/修订和等待；不是Bot自己扩增 |
| output | 程序 | task result固定路径、格式、当前T和mode对应的精简schema；无写文件工具则path=null并回聊天 |

数据新鲜度由配置按市场、来源和任务判定，不能全局规定一个分钟数。保留报价、持仓、财报和共识各自的时点。运行级snapshot_id定义材料边界；每个值仍保留其本身的日期。

task_inputs最小装配：T01附原论点、实际可比较的共识/指引和事件计算；T02附财务/分部及同业资料；T03附候选范围和明确的数量上限；T04附T02结果、可用估值方法定义与输入单位；T05附dataset说明、注册因子/协议及baseline，interpretation再附实验回执；T06附上游研究结果、报价/估值和可用持仓约束；T07附实际草稿、原文定位与校验回执；T08附冻结决定，outcome模式另附process结果和后续表现。资料可内嵌或以本轮确实可读取的文件附带，不能要求子Bot回忆父会话或凭空知道注册公式。

来源为空并不允许模型从训练记忆补实时事实。来源编号必须由程序分配或由明确的补证导入结果返回。原生工具只有URL、没有统一ID时，Bot返回URL+原始时间+定位的候选来源，标为unregistered；程序登记后重新校验，不允许模型将自造ID当已登记证据。

## 输出包

下面第一个JSON是外壳示意；`result`的真实业务键由T任务定义，不能原样提交空对象。完整可校验示例见本文件最后的synthetic-T03-01结果。

```json
{
  "task_id": "task-001",
  "task_type": "T03",
  "instruction_version": "0.3",
  "snapshot_id": "snapshot-001",
  "status": "partial",
  "answer": "一句中文回答本次问题。",
  "findings": [
    {
      "id": "F1",
      "statement": "可核查的主张或明确标注的解释。",
      "kind": "interpretation",
      "evidence_ids": ["E1"]
    }
  ],
  "missing": [
    {"item": "实际缺少什么", "affects": "具体限制哪部分结论", "required": true}
  ],
  "next_step": "一条最有价值的下一步。",
  "result": {}
}
```

- status仅为done/partial/blocked，表示任务完整性；不等于利好/利空或买卖观点。
- findings最多5条；kind为reported_fact/management_statement/analyst_opinion/rumor/calculated/interpretation/assumption。calculated仅用于实际程序计算结果。模型解释仍要引用所依据材料；新假设可以无证据ID，但必须kind=assumption且给依据/待验证点。
- done/partial的result按任务卡列出的业务键及随包的output.schema填写。blocked允许result=null，但必须解释核心缺项。含数值的解释引用calculation ID；程序检查结构化数值、单位和舍入误差。资料值引用source ID。
- 未知值用null；不写0、"N/A所以观望"或虚构完整数据。result可包含来源ID、计算ID和finding ID，但不得引用其他run的未声明材料。
- 完整业务输出可以是“无机会/无增量”。任务可以done，同时T06的research_stance为null、readiness=insufficient——前提是任务本身就是判断可用性；若原定必须完成估值而未完成，应为partial/blocked。

## 关键机械校验

程序检查task/type/version/snapshot、结果路径范围、必需键、枚举、来源/计算ID存在性、信息时点、结构化数字口径、依赖完成和重复提交。自然语言中的数值与关系还需提取比对及T07核对，不能声称JSON schema可证明全文正确。具体输出类型见 [result.schema.json](result.schema.json)；prepare只展开当前任务的schema随包附带，不让弱模型读取全部任务定义。共享common中的外壳用于指明基本结构；生产输出的具体子字段类型由随包schema确定。

除schema之外，import-result还必须检查：有数值价格条件却没有对应计算回执、使用不同snapshot的数字、上下界颠倒、将币值当收益率、与input的mode不一致、尚无实验却声称out_of_sample、process模式携带后验结果。这些需要输入上下文，不能用静态schema单独证明。

补证产生新快照时，程序创建子版本，并把子版本列入本task允许读取清单；旧快照不覆盖。结果必须指向实际使用的最终快照。`task_id`标识一次派发；重派使用新task_id，程序内部用logical_task_id关联同一业务节点及attempt。这样迟到结果不能冒充新一轮结果，不增加模型需要填写的字段。结果文件只是提议，import-result成功才算任务收件。

T06区分三层：

1. **标的研究意见**：可基于明确的期限/假设提出BUY/SELL/WATCH；证据不足时null而非假中性。
2. **当前价格条件**：必须有满足本任务新鲜度要求的报价和适用估值结果；缺这些可继续讲业务，不能算当前收益空间。
3. **账户动作/仓位比例**：必须有符合时效要求的真实持仓、基础币种、相关现金/敞口及用户约束版本；不齐时position_action=null。意图记录不代表执行成交。

估值assumptions经过程序格式/单位校验后只是validated_input，不是经济上正确或用户已批准。T07核查方法和理由，重大假设保留给用户判断。固定因子协议只允许登记模板和参数界限，程序冻结protocol_hash；未登记方案进入工程待办而不是运行任意代码。

## 完整离线示例：送样能否进入早期线索池

以下均为合成测试事实，虚构公司 TEST-OPTICS，不对应真实投资对象；available_tools为空，所以不得声称联网、计算或写文件。

```json
{
  "run_id": "synthetic-chain-01",
  "task_id": "synthetic-T03-01",
  "task_type": "T03",
  "instruction_version": "0.3",
  "mode": "early_leads",
  "subject": {"theme": "下一代互连组件", "entity": "TEST-OPTICS", "security_id": "TEST.OPT", "currency": "USD"},
  "question": "能否进入早期线索池？哪条下一证据最值得追踪？",
  "horizon": "未来12个月",
  "decision_at": "2026-09-20T12:00:00+08:00",
  "snapshot_id": "synthetic-snapshot-01",
  "prior": null,
  "task_inputs": {"candidate_limit": 3, "initial_candidates": ["TEST.OPT"]},
  "sources": [
    {"id": "E1", "type": "company_statement", "published_at": "2026-09-18T09:00:00+08:00", "known_at": "2026-09-18T09:05:00+08:00", "locator": "合成材料第1段", "excerpt": "公司表示已向两家客户提供样品，仍在测试，尚未签署量产订单。"},
    {"id": "E2", "type": "industry_report", "published_at": "2026-09-19T09:00:00+08:00", "known_at": "2026-09-19T09:05:00+08:00", "locator": "合成材料第2段", "excerpt": "新架构可能提高该类组件需求，但替代方案与客户认证进度尚不确定。"}
  ],
  "calculations": [],
  "constraints": {"scope": "只评价线索资格，不评价买入价格", "investment_policy": null},
  "available_tools": [],
  "budget": {"external_calls": 0, "evidence_requests": 2, "repair_attempts": 1},
  "deadline": "2026-09-20T12:10:00+08:00",
  "output": {"format": "json", "path": null}
}
```

支持的一种输出如下；不是唯一标准答案，重点是没有把送样升级成量产，也没有抹掉早期研究价值：

```json
{
  "task_id": "synthetic-T03-01",
  "task_type": "T03",
  "instruction_version": "0.3",
  "snapshot_id": "synthetic-snapshot-01",
  "status": "done",
  "answer": "可列为早期线索；目前仅有送样和潜在需求依据，尚不能确认瓶颈、订单或利润贡献。",
  "findings": [
    {"id": "F1", "statement": "公司披露仍在客户测试阶段，未签量产订单。", "kind": "management_statement", "evidence_ids": ["E1"]},
    {"id": "F2", "statement": "新架构可能增加需求，但替代路线和认证进度削弱确定性。", "kind": "interpretation", "evidence_ids": ["E1", "E2"]}
  ],
  "missing": [{"item": "认证与订单进度、有效产能及利润贡献", "affects": "后续投资判断；不阻止列入早期线索", "required": false}],
  "next_step": "追踪客户认证完成及量产订单的正式披露。",
  "result": {
    "system_map": [{"from": "新互连架构", "to": "组件需求", "relation": "可能提升", "evidence_ids": ["E2"]}],
    "bottleneck_hypothesis": {"mechanism": "未知，尚无产能/良率约束证据", "evidence_ids": ["E2"]},
    "candidates": [{"security_id": "TEST.OPT", "chain_role": "组件潜在供应商", "maturity_stage": "sampling", "exposure_evidence": ["E1"], "profit_hypothesis": null, "status": "lead", "next_proof": "认证结果与量产订单"}],
    "rejected_alternative": "材料不足以判定替代路线被排除。"
  }
}
```

## 程序计算示例的语义

测试用假设：一年后EPS情景为3/4/5，倍数为18/20/22；程序相乘得到54/80/110，币种USD。无分红、以基准终值80和要求回报10%反推入场上限为80/1.10≈72.73。这个例子只验证输入、算术、期限和字段传递；它没有证明10%回报要求合理，也没有证明公司价值或应当买入。T04解释模型适用性，T06再结合业务/风险证据作研究意见。
