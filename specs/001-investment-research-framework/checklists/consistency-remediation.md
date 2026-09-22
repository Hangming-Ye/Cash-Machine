# 2026-09-21 一致性问题修订与复查

用户已批准修复 speckit-analyze 报告的 6 项问题。本轮只改设计文档与任务说明，没有实现程序、迁移实际 Bot 或执行 61 项实施任务。

| ID | 修订结果 | 复查依据 |
| --- | --- | --- |
| I1 | 迁移清单改为实际 bot-kit/prompts/ 的共同指令及五个岗位文件；逐一改写或停用，部署核对加载版本 | tasks T012、contracts/bot-workflow、plan；不再创建错误的 roles/README 或重复 common 路径 |
| U1 | check artifact 默认只检查，显式 --archive 校验后固化 Decision／WorkRecord／Review 正文及附件并返回 ID；memory apply 不代替历史归档 | contracts/cli、data-model、tasks T007/T009 的基础入口及 T032/T033/T053 的完整报告集成、quickstart 的归档→经验更新顺序 |
| U2 | current／historical／review 三种任务级读取语义；known_at 由程序记录版本形成时间；历史按当时版本筛选，复盘原输入与后续材料分区 | contracts/cli、data-model、plan、tasks T011/T050/T051；增加迟形成经验、后来停用和缺历史版本样例 |
| I2 | T004 创建验收骨架，T061 可随时更新未执行／受阻情况；只有最终勾选与完成声明依赖 T057—T060 及所有 SC 通过 | tasks 行级依赖、依赖图、quickstart 的验收说明一致 |
| C1 | 六份请求模板分别由 T011/T022/T029/T032/T048 提供；T004 建测试 runner 骨架、T060 完成验证集成；返回 ID／版本自动填回 | tasks、quickstart；runner 仅为样例验证辅助，不成为生产调度器 |
| I3 | FactorExperiment 补齐 horizon、parameter_sets、primary_metric、failure_regimes 等字段，并引用完整冻结 request_ref／request_hash；复算拒绝摘要与请求不一致 | data-model、contracts/calculations、tasks T044 |

## 检查范围与结果

- 核对上述修订在 spec 目标、plan、research、模型、三个契约、tasks 和 quickstart 中的表述与调用顺序。
- 任务编号仍为 T001—T061，全部未勾选；21 项并行标记不变。T061 的持续记录与最终关闭分开，不制造依赖环。
- Markdown 本地链接、迁移源路径、模型／请求必需字段对齐及任务格式执行静态检查。
- 六项原问题在文档层已闭合；没有因此增加供应商、服务、数据库、任务状态机或额外业务范围。
- 旧 bot-kit/prompts 内容本轮不改写，其迁移是 T012 的实施工作；不能以本文为实际 Bot 已更新的证据。

本记录只证明文档修订与静态一致性复查。依赖锁、CLI、样例文件、真实数据、原生 Grok 行为与验收效果仍须实施后验证。
