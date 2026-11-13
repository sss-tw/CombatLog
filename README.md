# 卡塔赞战斗档案

本目录可直接作为 GitHub Pages 仓库根目录发布。

## 目录结构

```text
.
├─ index.html
├─ .nojekyll
└─ reports/
   └─ 2026-11-12/
      └─ index.html
```

## GitHub Pages 设置

1. 将本目录中的内容上传到仓库根目录。
2. 打开仓库的 **Settings → Pages**。
3. 在 **Build and deployment** 中选择 **Deploy from a branch**。
4. 选择包含这些文件的分支和 `/(root)`，保存。

网站内全部使用相对链接，可同时支持：

- `https://用户名.github.io/仓库名/`
- `https://用户名.github.io/`

## 添加新报告

在本地 `C:\wow-turtle` 中放入：

```text
karazhan-tower-YYYY-MM-DD.html
```

然后运行：

```powershell
python build_report_site.py
```

脚本会重新生成本目录的日期列表，并把报告放入对应日期目录。之后将本目录的变更上传到 GitHub 即可。
