# Bot 配置与作业包

版本0.3。用于补足岗位指令和固定金融任务，不是已经安装的Grok插件。所有文字为本项目独立编写。研究程序入口尚未实现，不能因为文档出现函数名就声称可调用。

## 先配置什么

| Bot | 常驻指令文件 | 可接作业 |
|---|---|---|
| 幕僚长 Chief | [chief.md](prompts/chief.md) | T06综合、T08复盘；选择5条固定流程 |
| 产业与公司 Research | [research.md](prompts/research.md) | T02公司、T03产业链、T04估值假设 |
| 市场与事件 Market | [market.md](prompts/market.md) | T01事件/财报/预期/宏观影响 |
| 单票因子 Quant | [quant.md](prompts/quant.md) | T05实验协议或结果解释 |
| 复核 Reviewer | [reviewer.md](prompts/reviewer.md) | T07引用、业务逻辑、数值一致性复核 |

每个Bot加载 [common.md](prompts/common.md) + 自己的角色文件；一次任务再附对应T文件和完整任务包。不要把全部角色、全部作业和全部研究报告一起加载。提示词使用英文便于统一工程维护，用户输出默认中文。

“system prompt”在此指常驻岗位指令的设计正文。Grok Bot公开文档未说明可直接替换原始system层；用Description承载岗位摘要，通过对话明确保存工作方式为私有skill，并在每次任务与Routine中明确引用。实际保存/加载效果必须用行为测试检查。API执行器才可以使用真正的system/developer消息。[官方Bot配置](https://docs.x.ai/grok-bot/bots) · [官方Skill机制](https://docs.x.ai/grok-bot/skills-routines-and-automations)

## 原生Bot部署步骤

1. 为现有Bot匹配上述职责；先保留现有记录，不删除Bot。
2. 在对应Bot配置中写入简短岗位描述。把common和role正文作为可信的用户指令交给Bot，明确保存成工作skill；不得仅让Bot自行总结一次便当作配置完成。
3. 给一个完整的离线任务包和相应T文件，验证它实际按步骤返回。检查输出而不是只接受“我记住了”。
4. 将验证后的作业保存为私有skill，命名例如 `invest-t01-event-impact-v03`；版本写在任务包里。保存后的skill需要核对，不允许省掉关键步骤。
5. 第二个不同输入也通过后，再创建Routine；Routine引用指定skill、输入来源、固定工作流、失败回执与预算，不只写“每天分析股票”。
6. 按 [evaluation.md](evaluation.md) 验证岗位、任务、程序和手机链路。没有程序时只做包内分析测试，禁用命令执行并标注计算尚缺。

如果原生界面无法保存完整内容，保留版本化文件，每次任务要求先读common、role、指定task文件；把是否真实加载纳入验收，不能宣称实现了强制注入。公开分享Bot可能包含配置，分享前另外审查，不将密钥/持仓包放入共享模板。

## 一次交接必须包含

task_id、task_type、目标对象及已解析身份、decision_at、研究问题、期限、资料与计算结果、上次判断、实际可用工具、输出路径、来源限制和budget。见 [contracts.md](contracts.md)。接收者应能在新会话里完成任务，不要求知道父会话、默认工作目录或其他Bot的思考过程。

## 两个可复制的调用外壳

**发给专员（由幕僚长填入真实任务包）：**

> Execute the supplied task only. Apply the common instruction, your role instruction, and task T01 v0.3. Read the attached complete task packet. The available-tools section is authoritative for this run; a named tool in documentation is not proof it exists. Return one result envelope using the specified fields. Save only to the assigned result path if file access is available; otherwise return the JSON in the chat and state that it was not saved. Send the task ID and actual result location back to Chief. Do not launch another Bot.

**Routine模板（配置时必须替换方括号，不可原样启用）：**

> Run workflow [daily-review] for [configured watchlist] at [exchange-calendar condition / timezone]. Use version [0.3] of the agreed workflow and role/task skills. Ask the configured research program to prepare the current snapshot and ready task packets. Dispatch only those packets to the mapped Bots. Import actual results, report unresolved or overdue tasks, and publish only the finalized output. Notify the user only for material changes or required action. If the research program is unavailable, return an operational failure; do not invent a daily investment report. Record the run and delivery status.

这些是配置模板，本次没有创建Routine或向其他应用发送消息。

## 文档入口

- [作业设计与程序分工](../BOT_OPERATING_SPEC.md)
- [八种任务卡](tasks/README.md)
- [数据契约与合成输入示例](contracts.md)
- [可机器校验的输出Schema](result.schema.json)
- [模型与运行验收案例](evaluation.md)
