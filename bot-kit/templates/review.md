# 历史判断复盘

## 复盘状态
- 状态：`due | triggered | not_due | not_triggered | inconclusive`
- 原判断 ID／截止：`<decision_id>`／`<decision_as_of>`
- 复盘截止：`<review_at>`
- 到期／触发依据与下次检查：<依据或缺口>

## 当时输入（冻结）
- 原结论、期限、条件、假设、价格／计算引用：<不可变引用>
- `memory_packet_refs` 及当时采用／拒绝内容：<实际路径和理由>
- 当时支持、反证和未知项：<来源定位>

## 后续事实与结果
- 截至 `review_at` 的事实／计算：<不可变引用>
- `observed_outcome`：<已观察结果；未知执行仍为未知>
- 反证与未解决冲突：<材料和限制>

## 过程归因与下一步
- `process_findings`：<资料、预测、推理、执行、市场路径分别说明>
- `counterevidence`：<最强反方材料>
- 受影响假设／依赖、需重算项和下一验证点：<实际动作>

上面的 `due/not_due/...` 是叙述状态，不是 Review 模型字段。Review JSON 草稿形状：

```json
{
  "review_id": "draft-review",
  "decision_id": "<RETURNED_DECISION_ID>",
  "decision_as_of": "<AWARE_ISO_TIME>",
  "review_at": "<AWARE_ISO_TIME>",
  "observed_outcome": "<TEXT>",
  "process_findings": ["<TEXT>"],
  "counterevidence": ["<TEXT>"],
  "lesson_refs": ["<EXISTING_IMMUTABLE_LESSON_REF>"]
}
```

新经验不能在 Review 归档前循环写入 `lesson_refs`。检查请求形状为 `{"request_id":"<CALLER_REQUEST_ID>","draft_ref":"<WORKSPACE_RELATIVE_REVIEW_JSON>","record_type":"Review","reference_refs":["<ACTUAL_IMMUTABLE_REF>"]}`；是否支持报告正文／附件字段以当时 T032 实际接口为准。

```text
uv run --project <VERIFIED_APP_DIR> cash-research --root <DATA_ROOT> check artifact --request <REVIEW_CHECK_REQUEST.json> --archive
```

只有实际返回的 immutable Review ID／路径可供后续 `memory apply`。记录本次记忆采用／拒绝理由、归档失败和仍需补证项。
