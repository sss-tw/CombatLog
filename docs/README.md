# 本地战斗日志分析工具：接手入口

本目录用于在 `C:\Users\sekilai\Documents\CombatLog` 重新打开仓库后，继续开发可复用的卡塔赞之塔战斗日志分析工具。目标是把确定性的日志解析和统计放到本地执行，让 AI 只复核高风险归因与异常结果，减少重复读取整份日志产生的 Token 消耗。

## 文档索引

- [START_PROMPT.md](START_PROMPT.md)：在新目录、新对话中直接使用的启动提示词。
- [LOCAL_TOOL_PLAN.md](LOCAL_TOOL_PLAN.md)：本地工具架构、迁移步骤和交付顺序。
- [ANALYSIS_RULES.md](ANALYSIS_RULES.md)：当前已经确认的统计口径。
- [AI_REVIEW_PROTOCOL.md](AI_REVIEW_PROTOCOL.md)：AI 如何用精简证据包检查本地结果。
- [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md)：回归测试和发布前验收条件。

## 当前系统

当前分析代码仍位于 `C:\wow-turtle`：

- `analyze_karazhan_today.py`：日期专用分析脚本，包含日志解析、职责识别和全部机制统计。
- `render_karazhan_canvas.py`：把分析 JSON 转换为统一展示模型、Canvas 和 HTML。
- `build_report_site.py`：把展示数据复制到本网站目录并更新日期索引。
- `卡塔赞战斗日志统计规范.md`：旧版完整规则文档。

网站目录：

```text
C:\Users\sekilai\Documents\CombatLog
├─ assets/
├─ reports/
│  ├─ 2026-11-12/
│  └─ 2026-11-18/
├─ docs/
│  ├─ README.md
│  ├─ START_PROMPT.md
│  ├─ LOCAL_TOOL_PLAN.md
│  ├─ ANALYSIS_RULES.md
│  ├─ AI_REVIEW_PROTOCOL.md
│  └─ ACCEPTANCE_CHECKLIST.md
├─ index.html
└─ README.md
```

## 当前基准

`2026-11-18` 是新工具的首个黄金基准。新实现必须先复现当前分析 JSON 和网页中的全部结论，再允许用于新日期。

基准中特别容易误判的项目包括：

- 职责按技能识别，不能固定坦克或治疗人数。
- 阿诺玛鲁斯奥术超载可能由一人正常结算引发多名超载持有者死亡并连锁爆炸；个人排行按根因归责。
- 桑夫的裂隙诅咒只在裂隙回馈致死时追责；裂隙纠缠是另一项机制。
- 库鲁尔高层冷漠打击由四名轮换坦克中的未接手两人负责。
- 同名小怪没有 GUID 时必须保留推断说明，不能伪造精确归属。

## 新仓库开始后的第一步

1. 不要立即重写所有规则。
2. 先把 `2026-11-18` 的输入、分析 JSON 和展示 JSON固定为测试夹具。
3. 建立本地命令行入口与 JSON Schema。
4. 逐模块迁移，每迁移一项就与黄金结果比较。
5. 所有自动检查和 AI 复核通过后，再替换旧脚本。

## Git 操作约束

文档和本地代码修改不自动提交或推送。只有用户明确要求 `commit` 才提交，明确要求 `push` 才推送；提交中不得包含 AI、Cursor 或自动生成作者标记。
