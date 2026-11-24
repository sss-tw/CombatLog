# 卡塔赞战斗档案

本目录可直接作为 GitHub Pages 仓库根目录发布。

## 分析工具文档

本地分析工具的重构计划、完整统计规则、AI复核协议和验收清单位于 [`docs/README.md`](docs/README.md)。

未来推荐流程：

```text
原始日志 → 本地确定性分析 → 自动校验 → AI精简复核 → 生成网站数据 → 发布
```

AI只复核灭团原因、复杂因果、低置信度结论和黄金结果差异，不再默认读取整份日志。

## 目录结构

```text
.
├─ assets/
│  ├─ report.css
│  └─ report.js
├─ index.html
├─ .nojekyll
└─ reports/
   └─ YYYY-MM-DD/
      ├─ index.html
      └─ data.json
```

`assets/` 是所有新报告共用的模板样式和渲染逻辑；每个日期目录只保存通用页面入口与当日数据。修改模板后，所有采用新结构的报告会同时生效。

## GitHub Pages 设置

1. 将本目录中的内容上传到仓库根目录。
2. 打开仓库的 **Settings → Pages**。
3. 在 **Build and deployment** 中选择 **Deploy from a branch**。
4. 选择包含这些文件的分支和 `/(root)`，保存。

网站内全部使用相对链接，可同时支持：

- `https://用户名.github.io/仓库名/`
- `https://用户名.github.io/`

## 添加新报告

先生成当日的展示数据：

```powershell
python render_karazhan_canvas.py karazhan_YYYYMMDD_analysis.json
```

脚本会在 `C:\wow-turtle` 生成：

```text
karazhan-tower-YYYY-MM-DD.data.json
```

再运行：

```powershell
python build_report_site.py
```

脚本会复用公共模板、复制当日数据并更新日期列表。`2026-11-12` 是迁移前的旧版静态页面，后续报告使用数据与模板分离结构。
