# 卡塔赞战斗日志本地分析工具计划

## 1. 目标

将当前依赖 AI 反复读取大体积日志的流程改为：

```text
WoWCombatLog + WoWRawCombatLog + CustomData + 当周配置
                ↓
       本地确定性分析工具
                ↓
 analysis.json + evidence.json + review-pack.json
                ↓
        自动校验 + AI 精简复核
                ↓
          网站展示数据与归档
```

要求：

1. `2026-11-18` 最终统计结果与当前网站一致。
2. 简单解析、计数、时间窗关联、伤害求和和阈值判断全部在本地完成。
3. 每条结论都能追溯到原始日志行。
4. AI 不需要读取整份日志，只读取异常项的证据片段。
5. 低置信度归因必须显式标记，不得静默猜测。
6. 自动校验或 AI 复核失败时禁止发布。

## 2. 建议技术方案

使用 Python 标准库优先，兼容当前 Windows 环境，不引入数据库服务。

```text
src/karazhan_tool/
├─ __main__.py
├─ cli.py
├─ config.py
├─ model.py
├─ parser/
│  ├─ combat_log.py
│  └─ custom_data.py
├─ core/
│  ├─ roster.py
│  ├─ roles.py
│  ├─ windows.py
│  ├─ auras.py
│  └─ evidence.py
├─ rules/
│  ├─ common.py
│  ├─ buffs.py
│  ├─ consumables.py
│  ├─ curses.py
│  ├─ narmuun.py
│  ├─ intagos.py
│  ├─ anomalus.py
│  ├─ medivh.py
│  ├─ king.py
│  ├─ sanf.py
│  ├─ rupturan.py
│  ├─ kruul.py
│  └─ mephistroth.py
├─ summary.py
├─ validate.py
└─ review_pack.py

config/
├─ rules.json
├─ equipment_arcane_resistance.json
└─ raids/
   └─ 2026-11-18.json

tests/
├─ fixtures/2026-11-18/
├─ golden/2026-11-18/
├─ test_parser.py
├─ test_rules.py
└─ test_golden.py
```

## 3. 命令行接口

```powershell
python -m karazhan_tool analyze --config config/raids/2026-11-18.json
python -m karazhan_tool validate output/2026-11-18/analysis.json
python -m karazhan_tool review-pack output/2026-11-18/analysis.json
python -m karazhan_tool render output/2026-11-18/analysis.json
python -m karazhan_tool publish --date 2026-11-18
```

也应提供一次完成的入口：

```powershell
python -m karazhan_tool run --config config/raids/2026-11-18.json
```

`run` 的执行顺序固定为：

1. 读取输入并计算文件哈希。
2. 从 CustomData、GUID、团队快照和配置冻结本场玩家名单。
3. 使用冻结名单解析日志为标准事件，再识别职责。
4. 执行通用与逐 Boss 规则。
5. 生成错误汇总。
6. 自动校验。
7. 生成 AI 证据包。
8. 等待或读取 AI 复核结果。
9. 通过后生成网站数据。

## 4. 当周配置

日期专用信息只能放在配置文件，不得写死在规则代码中。

```json
{
  "date": "2026-11-18",
  "combat_log": "C:\\wow-turtle\\Logs\\WoWCombatLog.txt",
  "raw_combat_log": "C:\\wow-turtle\\Logs\\WoWRawCombatLog.txt",
  "custom_data": "C:\\wow-turtle\\CustomData\\VanillaWCL_Basin_of_Stars_旧德二世.txt",
  "raid_start": "19:24:07.050",
  "raid_end": "20:55:10.466",
  "logger_identity": {
    "guid": "由当周数据填写",
    "name": "由当周数据填写"
  },
  "roster_overrides": [],
  "encounters": [],
  "raid_groups": {},
  "class_overrides": {},
  "role_overrides": {},
  "curse_assignments": {}
}
```

以上是2026-11-18黄金基准当前使用的只读外部输入。普通日志提供可读事件，RAW日志提供GUID和技能ID，CustomData提供团队快照及GUID映射。三者均计算文件哈希并按时间对齐。大型原始日志不进入Git；若以后移动文件，只修改日期配置。Boss 时间可以由工具自动发现，但必须允许配置覆盖。自动发现与人工覆盖同时保存到结果中，便于 AI 检查差异。

## 5. 名单优先解析

日志事件解析前先建立不可变的玩家表：

```json
{
  "guid": "Player-...",
  "name": "你的寒冰箭",
  "class": "MAGE",
  "sources": ["custom_data", "raid_snapshot"],
  "confirmed": true
}
```

解析器必须：

1. 优先按 GUID 绑定来源和目标。
2. 无 GUID 时，在冻结名单中执行完整姓名最长匹配。
3. 结合事件模板判断姓名、所有格和技能字段边界。
4. 对“你”“你的”“你的XXX”同时生成合法候选，不能先做字符串替换。
5. 只有语法明确且没有同名玩家候选时，才把第二人称代词映射到 `logger_identity`。
6. 无法唯一确定时输出候选列表和 `ambiguous_name`，交 AI 复核。

建议将名字解析单独实现为 `parser/names.py`，并使用包含以下姓名的测试夹具：

- `你`
- `你的`
- `你的寒冰箭`
- 普通姓名
- 一个姓名是另一个姓名前缀的两名玩家

## 6. 标准事件模型

日志只解析一次，后续规则不得重复使用大量正则扫描原始文本。

```json
{
  "line": 175894,
  "timestamp": "19:50:53.024",
  "seconds": 71453.024,
  "type": "AURA_REMOVED",
  "source": null,
  "target_guid": "Player-...",
  "target": "示例玩家",
  "spell": "奥术超载",
  "amount": null,
  "school": null,
  "name_resolution": "guid",
  "raw": "奥术超载效果从示例玩家身上消失。"
}
```

至少支持：

- 伤害、治疗、法力变化。
- 光环获得、叠层、消失和驱散。
- 施法开始、成功、失败、中断和嘲讽。
- 死亡、免疫、抵抗、吸收。
- 宠物与主人归属。
- 高级日志的 GUID、队伍、装备和光环快照。

## 7. 证据优先的规则输出

每条规则结果必须包含：

```json
{
  "finding_id": "anomalus.overload.008",
  "rule_id": "anomalus.overload_explosion",
  "player": "Tbug",
  "status": "error",
  "weight": 1,
  "values": {
    "raid_damage": 184139,
    "hit_players": 36,
    "average_damage": 5115.0
  },
  "evidence": [
    {"line": 173578, "purpose": "获得奥术超载"},
    {"from": 175754, "to": 175893, "purpose": "连续爆炸批次"},
    {"line": 175894, "purpose": "超载消失"}
  ],
  "confidence": "high",
  "assumptions": [
    "按根因将后续超载持有者死亡产生的连锁爆炸归给首次触发者"
  ]
}
```

规则不得只输出最终数字而不保存证据。

## 8. 确定性与人工判断边界

本地工具负责：

- 事件解析、时间换算、窗口切分。
- 伤害、治疗、命中、死亡和施法次数。
- Buff、Debuff、药剂和诅咒覆盖率。
- 明确阈值与豁免规则。
- 个人错误加权、排序和零错误成员。
- 页面展示模型和日期归档。

AI负责：

- Boss 边界或阶段无法唯一确认时的复核。
- 同名无 GUID 小怪的归属检查。
- 灭团根因与连锁后果区分。
- 多个驱散或爆炸在同一时间窗口时的因果判断。
- 职责识别异常和配置覆盖建议。
- 新机制、未知技能和历史日志交叉验证。

## 9. 迁移步骤

### 阶段 A：冻结基准

1. 保存 2026-11-18 当前分析 JSON、展示 JSON和网页。
2. 对 JSON 排序并生成 SHA-256。
3. 建立关键指标清单：团队人数、职责、DPS、每项机制、排行和灭团总结。

### 阶段 B：抽取解析器

1. 从旧脚本迁移时间、单位、宠物和伤害解析。
2. 输出标准事件 JSONL。
3. 对关键日志行写单元测试。
4. 此阶段不改变任何规则。

### 阶段 C：迁移公共模块

依次迁移：

1. 团队名单和职责。
2. DPS与战斗窗口。
3. Buff、祝福和风怒。
4. 诅咒、驱散和消耗品。

每迁移一项就与黄金结果比较。

### 阶段 D：迁移 Boss 规则

按低风险到高风险迁移：

1. 因塔苟斯、破碎者、孟菲斯托斯等明确目标统计。
2. 纳尔穆恩、麦迪文、国王。
3. 桑夫、库鲁尔、阿诺玛鲁斯等复杂时间窗和因果规则。

### 阶段 E：AI复核与发布

1. 生成 `review-pack.json`。
2. AI输出 `review-result.json`。
3. 自动校验复核结果对应当前输入哈希。
4. 全部通过后才写入 `reports/YYYY-MM-DD/data.json`。

## 10. 兼容策略

- 旧脚本保留到新工具完整通过黄金测试。
- 新工具先只读，不直接覆盖网站。
- 使用 `--compare-old` 同时运行新旧实现并生成差异报告。
- 差异分为：结构差异、数值差异、排序差异、文案差异和证据差异。
- 任何非预期差异必须人工确认并记录规则变更原因。

## 11. 完成定义

满足以下条件才算完成：

- 新日期只需新增配置和输入文件。
- 2026-11-18 的全部结果通过黄金测试。
- 每项个人错误都有日志证据。
- AI只读取 `review-pack.json` 和按需展开的片段。
- 验证失败时不会修改网站。
- 本地一次命令可生成分析、证据、复核包和网站数据。
