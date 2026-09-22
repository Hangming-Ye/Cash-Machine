# Cash Machine

面向个人投资研究的框架，覆盖供应链机会探索、单票因子研究、持仓与自选综合判断。以Grok Bot的常驻、定时、多Agent和手机访问为主要使用场景；复杂且需要确定性的执行交给程序。

## 当前阶段

本地已有可安装的 `cash-research` 包（版本 **0.1.0**）与 CLI 命令组：`data`、`compute`、`memory`、`check`。本机可用合成 fixtures 复走验证链；不声称原生 Grok 行为、live 券商读数或云端部署已通过。

- **当前规格与计划**：[spec001](specs/001-investment-research-framework/spec.md)、[plan](specs/001-investment-research-framework/plan.md)、[新增选择审批表](specs/001-investment-research-framework/plan-assumptions.md)。
- **需求依据**：[docs/intent.md](docs/intent.md)。
- **调研入口**：[RESEARCH_INDEX_20260920.md](RESEARCH_INDEX_20260920.md)。
- **候选方案**：[BOT_OPERATING_SPEC.md](BOT_OPERATING_SPEC.md)、[架构研究](FINANCIAL_RESEARCH_ARCHITECTURE_20260920.md)、[bot-kit](bot-kit/README.md)。这些是设计输入，不是已批准spec。
- **旧项目参考**：[archive/sec-analysis-20260920](archive/sec-analysis-20260920/ARCHIVE.md)。
- **来源缺口**：现有六源为 Finnhub、Tiingo、FMP stable、AKShare、IBKR Flex、Longbridge OAuth。G-01—G-08 仍记录在 [data-sources.md](specs/001-investment-research-framework/data-sources.md)，不是已消除缺口。

原代码复用优先级低。新实现可独立设计，也可局部改造旧模块，不承担兼容旧接口或目录结构的义务。

## Spec Kit

已使用本机Spec Kit **1.0.1**的内置模板初始化，脚本类型为PowerShell，集成为Codex skills，并安装Git扩展。

| 目录 | 内容 |
|---|---|
| `.specify/` | 模板、PowerShell脚本、工作流和Git扩展 |
| `.agents/skills/` | 项目级Spec Kit技能 |
| `specs/` | 后续正式功能规格、计划与任务 |
| `docs/` | 已对齐intent及项目文档 |
| `research/` | 调研与源码阅读记录 |
| `bot-kit/` | 候选岗位指令、任务卡和输出契约 |
| `archive/` | 仅供参考的旧实现 |

`.specify/memory/constitution.md`已整理用户明确的约束，不批准plan新增技术选择。任务清单见 [tasks.md](specs/001-investment-research-framework/tasks.md)。旧方案的固定岗位数、流程或上限不是现行约束。

## Git与本地配置

沿用原仓库的`main`分支、提交历史和`origin`。初始化与归档只在本地提交，不自动推送远端。

本地凭证文件`sec-analysis.env`保留在原位置并被Git忽略；它不属于归档或新项目的默认配置，也不会被 CLI 隐式加载。`data/` 运行时目录同样被忽略。发布 zip 生成在 `tmp/releases/`，属于临时产物而非源码。不要将凭证、账户数据或运行缓存加入版本控制。
