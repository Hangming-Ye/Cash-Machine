# 固定金融任务卡 v0.3

只加载本次任务，不要求Bot记忆整本手册。所有任务同时使用common和对应role。任务类型不同只改变`result`内的业务字段；外层输入输出契约一致。

| ID | 文件 | 角色 | 必须回答的问题 |
|---|---|---|---|
| T01 | [event-impact.md](event-impact.md) | Market | 新事实/预期/价格各改变了什么？ |
| T02 | [company-thesis.md](company-thesis.md) | Research | 什么业务驱动能产生可持续利润与现金流？ |
| T03 | [supply-chain.md](supply-chain.md) | Research | 真正瓶颈与潜在受益公司是什么，处于什么阶段？ |
| T04 | [valuation.md](valuation.md) | Research | 用什么假设和方法估值，当前价格隐含什么？ |
| T05 | [factor-study.md](factor-study.md) | Quant | 一个因子是否改善指定的主观交易决策？ |
| T06 | [decision-brief.md](decision-brief.md) | Chief | 综合后买/卖/观望的依据与价格条件是什么？ |
| T07 | [review.md](review.md) | Reviewer | 来源和计算是否真正支持关键结论？ |
| T08 | [retrospective.md](retrospective.md) | Chief | 当时判断的质量与后来结果分别如何？ |

每个字段允许明确的unknown/null和缺口说明，不允许为了填满表格发明事实。输入包选择了任务mode时只做对应mode；不知道mode则返回精确缺项，不把提案与验证混成一次自我证明。
