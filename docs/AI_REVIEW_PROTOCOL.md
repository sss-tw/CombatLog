# AI 精简复核协议

## 1. 目的

本地工具负责确定性计算，AI只复核高风险结论。AI默认不读取完整战斗日志，而是读取带原始行号和上下文的精简证据包。

复核必须能回答：

1. 证据是否支持结论。
2. 规则是否用对。
3. 是否存在重复计错或错误豁免。
4. 灭团原因与连锁后果是否区分正确。
5. 与黄金结果的变化是否合理。

## 2. 输入文件

`review-pack.json` 至少包含：

```json
{
  "schema_version": 1,
  "date": "2026-11-18",
  "input_hashes": {
    "combat_log": "sha256:...",
    "raw_combat_log": "sha256:...",
    "custom_data": "sha256:...",
    "config": "sha256:..."
  },
  "summary": {},
  "role_assignments": [],
  "findings": [],
  "wipe_timelines": [],
  "golden_diff": {},
  "warnings": []
}
```

每项发现必须包含：

```json
{
  "finding_id": "kruul.mark_dispel.002",
  "rule_id": "kruul.mark_dispel",
  "encounter_id": "kruul.01",
  "player": "旧德二世",
  "target": "小卓大美丽",
  "weight": 1,
  "values": {
    "damage": 6000
  },
  "window": {
    "start": "20:41:10.000",
    "end": "20:41:12.000"
  },
  "evidence_lines": [
    {
      "line": 330001,
      "timestamp": "20:41:10.800",
      "raw": "……",
      "purpose": "印记被解除"
    },
    {
      "line": 330010,
      "timestamp": "20:41:10.900",
      "raw": "……",
      "purpose": "高伤暗影新星"
    }
  ],
  "confidence": "high",
  "assumptions": []
}
```

## 3. AI必须复核的内容

完整复核以下项目：

- 每次灭团的直接原因、放大因素和时间线。
- 一次造成4人及以上死亡或异常高额团伤的机制。
- `confidence` 为 `low` 或 `medium` 的结论。
- 职责冲突、未知职责或人工覆盖。
- `ambiguous_name` 姓名歧义，特别是“你”“你的”“你的XXX”与第二人称日志语法冲突。
- 与黄金结果不一致的规则结果。
- 错误排行或灭团错误排行发生变化。
- 连锁爆炸、同秒驱散、光环消失顺序倒置等因果归属。
- 新出现、未映射或仅从历史记录推断的技能。

抽样复核以下项目：

- Buff与药剂覆盖率的起止边界。
- 普通输出、施法次数和DPS。
- 明确的一对一驱散。
- 0错误成员和豁免成员。

## 4. 按需展开证据

如果精简证据不足，AI按 `finding_id` 请求局部片段，不读取全文：

```powershell
python -m karazhan_tool evidence ^
  --finding anomalus.overload.008 ^
  --before 3 ^
  --after 3
```

允许请求：

- 指定发现的额外上下文。
- 指定时间范围。
- 指定玩家、技能或目标。
- 同一阶段的光环、伤害或死亡子集。

每次展开需记录请求原因，避免无边界地重复读取。

## 5. 复核判定

每项发现使用以下状态：

- `approved`：证据和规则均正确。
- `rejected`：结论错误，不应进入最终结果。
- `needs_change`：机制成立，但玩家、次数、权重、数值或文案需修正。
- `needs_evidence`：现有证据不足。

置信度含义：

- `high`：日志直接包含触发者、目标和结果。
- `medium`：需要时间窗关联，但没有同窗竞争事件。
- `low`：存在多个可能触发者、缺失GUID、职责或阶段不确定。

AI不得把低置信度猜测直接改为确定事实。
AI复核姓名时必须查看冻结名单、GUID、事件字段候选和原始文本；不得仅凭“你/你的”字样归给日志记录者。

## 6. 输出格式

AI输出 `review-result.json`：

```json
{
  "schema_version": 1,
  "date": "2026-11-18",
  "input_hashes": {
    "review_pack": "sha256:..."
  },
  "status": "approved",
  "reviewed_at": "2026-11-19T00:00:00+08:00",
  "items": [
    {
      "finding_id": "kruul.mark_dispel.002",
      "status": "approved",
      "reason": "印记解除后0.1秒出现单次6000暗影新星，符合高伤版阈值。",
      "correction": null
    }
  ],
  "global_issues": [],
  "requested_evidence": []
}
```

若需修正：

```json
{
  "finding_id": "example.001",
  "status": "needs_change",
  "reason": "该玩家是当前主坦克，规则规定豁免。",
  "correction": {
    "action": "remove",
    "fields": {}
  }
}
```

## 7. 发布门禁

满足以下全部条件才允许发布：

1. `review-result.json` 的输入哈希与当前证据包一致。
2. 没有 `rejected`、`needs_change` 或 `needs_evidence`。
3. 没有未处理的全局问题。
4. 自动验收清单全部通过。
5. 网站数据由已复核的分析结果生成，不能手工维护另一份数字。

输入日志、配置或规则代码变化后，旧复核结果立即失效。

## 8. 推荐的最小AI上下文

一次常规复核只提供：

- 本文。
- 当前规则版本号和变更摘要。
- 团队职责表。
- `review-pack.json`。
- 黄金结果差异。
- 必要的局部日志片段。

不要默认提供：

- 完整战斗日志。
- 完整旧对话。
- 与本周无关的历史战斗。
- 已通过确定性单元测试的普通计数明细。
