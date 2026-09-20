# Cash Machine

面向个人投资研究的框架，覆盖供应链机会探索、单票因子研究、持仓与自选综合判断。以Grok Bot的常驻、定时、多Agent和手机访问为主要使用场景；复杂且需要确定性的执行交给程序。

## 当前阶段

项目已初始化，intent已对齐；尚未生成正式功能spec，也没有新框架的运行实现。

- **需求依据**：[docs/intent.md](docs/intent.md)。
- **调研入口**：[RESEARCH_INDEX_20260920.md](RESEARCH_INDEX_20260920.md)。
- **候选方案**：[BOT_OPERATING_SPEC.md](BOT_OPERATING_SPEC.md)、[架构研究](FINANCIAL_RESEARCH_ARCHITECTURE_20260920.md)、[bot-kit](bot-kit/README.md)。这些是设计输入，不是已批准spec。
- **旧项目参考**：[archive/sec-analysis-20260920](archive/sec-analysis-20260920/ARCHIVE.md)。

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

`.specify/memory/constitution.md`目前是官方占位模板，尚未制定或批准项目constitution。接下来按intent形成constitution及功能spec，再进入plan/tasks；不把旧方案中的岗位数量、技术栈或执行上限直接冻结为需求。

## Git与本地配置

沿用原仓库的`main`分支、提交历史和`origin`。初始化与归档只在本地提交，不自动推送远端。

本地凭证文件`sec-analysis.env`保留在原位置并被Git忽略；它不属于归档或新项目的默认配置。归档保留无凭证的`.env.example`和原始依赖锁文件。不要将凭证、账户数据或运行缓存加入版本控制。
