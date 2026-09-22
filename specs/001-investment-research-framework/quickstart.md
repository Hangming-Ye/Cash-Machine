# Quickstart 与验收路径（实施后使用）

本文件描述目标执行方式，**当前只有设计文档，命令、fixtures 与测试尚未实现**。Plan 已批准，完成相应实施任务后才执行；不能把下列命令当作本轮已跑结果。

## 1. 环境与安装

目标为 Grok Bot 的共享云电脑。先记录产品版本、可用的 Skill／Routine／终端入口和 Python 环境；原生模型信息不可见时记录不可见。在私有工作区保存 bot-mapping.json：现有 Bot／Routine 的名称或可用标识、职责、Skill 入口、资料路径及主题写入负责人。确认 `/workspace/cash-machine/` 为私有项目目录，并按用户现有配置取得只读凭证来源，不在聊天粘贴秘密。

实施后的项目应有 pyproject.toml、uv.lock、fixtures 及实际 CLI。进入部署的 app 目录后执行：

```sh
uv sync --locked
uv run cash-research --help
uv run pytest tests/unit tests/contracts
```

若依赖或 Python 不兼容，先按锁文件及安装说明修复，不靠 Bot 临时改版本凑通。Windows 开发环境可执行同类离线命令，但不替代云端运行证据。

## 2. 合成材料的首个完整样例

实现应提供下列固定、无秘密的请求文件，内容满足 data-model 和 contracts；其数值结果包含可手算的 expected 产物：

```text
fixtures/requests/
  evidence-ingest.json
  memory-recall.json
  valuation.json
  factor-new-combination.json
  memory-update.json
  report-check.json
fixtures/scenarios/
  periodic-delta/
  long-term-thesis/
  deep-analysis-revision/
```

实现后用以下入口执行完整样例（runner 由 T004 建骨架、T060 完成集成）：

```sh
uv run python scripts/run_fixtures.py --root /workspace/cash-machine-test --case all
```

runner 在该测试 root 下创建独立运行目录，使用仓库中的六份请求模板，按以下顺序调用 CLI 并将返回 ID／版本填入下一请求：data ingest → memory recall → compute valuation → compute factor → check artifact --archive → memory apply。report-check.json 是包含合成 Decision／WorkRecord／Review 草稿的检查请求模板，runner 逐条实例化并归档；正文和所需附件固化后才供经验引用。原始模板不被运行结果覆盖。

模板任务归属：T022 的 evidence-ingest.json、T011 的 memory-recall.json／memory-update.json、T029 的 valuation.json、T048 的 factor-new-combination.json、T032 的 report-check.json。每份模板所需的合成来源／数据表由相应任务同时提供，runner 不造金融计算结果。

runner 记录每步命令、实际输入／输出与预期对照；任何失败明确报出，不继续伪造下游 ID。初始记忆可为空，应用更新时填实际 expected_version。重复运行使用新的测试运行目录，不覆盖前次结果；运行范围限测试 root，真实账户数据不参与此样例。它只是离线／合成验证辅助，不成为生产调度器。

通过：取数材料出处保留；数值与 expected 一致；合法新因子组合被运行而非退回开发；主题更新可回查旧版；缺字段／越界路径／任意代码字符串被拒绝；artifact 检查不声称金融语义正确。

## 3. 原生 Grok 入口验证

在现有 Bot 上配置草案 Description 和研究 Skill，先手工跑合成案例；无需新建 Bot。示例请求：

> 使用投研方法读取给定的虚构公司材料及相关经验，解释本轮变化、支持与反证、价格条件和下一验证点。需要计算时使用既定命令；完成后将判断草稿用 check artifact --archive 归档，再更新该测试主题摘要。结果在本会话交付，保留来源。

从新会话、隔离的测试 Routine、另一专员原生交接分别调用同一方法。测试 Routine 在现有 Bot 上临时创建，保持计划禁用，指令明确指向 /workspace/cash-machine-test 与合成输入，只用 Test run；先检查指令与路径及生产研究文件的版本／摘要，再执行，结束后核对生产文件未改；测试项不接真实来源。不得默认现有生产 Routine 支持单次路径覆盖，也不修改其生产计划。若产品不能禁用后单次试跑，暂用手工同指令验证并将 Routine 项标未通过，不能冒称测试完成。

通过：实际读取相关材料并在研究中使用；专员无父会话也能完成；输入和结果归属正确；手机和 PC 查看相同内容。失败分清入口未调用、资料未取到、压缩错误或读到但未使用；先修方法和入口，不增加调度系统。

## 4. 现有来源只读验证（覆盖探测在完整功能实施前执行）

为每个现有 source 建私有请求文件，不含秘密：

```sh
uv run cash-research --root /workspace/cash-machine --config /private/path/settings.json data fetch --request /private/path/positions-request.json
```

这里 `/private/path/` 是部署者替换的受保护实际路径，不是要求创建固定系统目录。凭证通过环境或显式 env-file 读取，禁止回显。

分别验证 Finnhub 报价／新闻、Tiingo US 日线、FMP stable 公司／财报、AKShare CN 数据、IBKR Flex、长桥账户／持仓／成交；长桥自选先检查云端现有实现。记录权限、时间、单位、覆盖、空值／失败／部分成功。真实结果仅私有保存，可脱敏交验收。

通过：实际持仓进入研究输入，Flex 明确 T+1；账户失败不等于空仓；数据不足出具体 G-xx 缺口。港股历史、复权、PIT、研报／社交等按 data-sources.md 先查已有源及网页原披露。允许从现有源导出或可追溯公开材料导入完整序列；补不到时提前报告哪项完整案例受阻，保持该项未通过，不能静默扩源或把受限案例算作通过。

## 5. 三类能力与记忆验收

| 场景 | 检查 |
| --- | --- |
| 供应链 | 只有主题即可发现并验证公司，保留排除／无机会结论；不能只改写新闻 |
| 持仓／自选 | 账户与行情时点清楚，结论有依据，估值／条件与期限可解释；冲突不隐去 |
| 因子 | 新组合无需开发改码；截断未来不改变历史特征，留出样本未用于选择；记录全部试验，允许无增量 |
| 定时记忆 | 两轮重复材料后加入一条变化：不重复创造经验，变化有来源，旧价格不当当前值；historical 不得读入截止后才形成的经验 |
| 长期记忆 | 多轮出现支持、反证和旧路径失效，新会话能从下一验证点接续 |
| 重分析记忆 | 更正股本或关键假设，能回查并重新计算，不机械引用旧摘要；review 将原判断输入与后来事实分区 |
| 跨问题经验 | 换措辞／换公司但同类问题可召回检查项；不适用、过时和弱证据不因相似就被采用 |
| 并发与简单重跑 | 两个任务各自产物明确；同主题摘要冲突返回版本错误并回读合并；失败重跑不覆盖旧判断 |

按 spec SC-001—008 完成 9 个核心案例、8 类异常、三类专员独立执行与 3 条复盘。样例数量沿用已批准方案中的基线，不代表有利润保证。对“无经验／有经验”比较是否补上历史暴露的分析遗漏，不强求措辞一致或建议改变。

## 6. 验收记录

保存产品／程序／配置版本、输入定位、数据时点、命令结果、可见工具读取记录、实际交给专员的记忆、最终报告及问题。分别标明文档检查、合成／mock、真实数据、真实 Grok 行为。

最终通过要求研究能完成且有参考依据。若某市场历史数据缺口导致完整案例不成立，明确未完成；不更改报告标签伪装完成，不因本轮限制来源而偷偷采购新服务。

验收汇总 acceptance.md 自 T004 创建后持续更新，未执行和受阻情况也要记录，不等待九个案例通过。只有全部成功标准及 T057—T060 完成，T061 才能勾选并宣布最终完成。
