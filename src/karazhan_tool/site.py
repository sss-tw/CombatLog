"""发布门禁与网站写入。只有显式确认且全部门禁通过才写 reports/。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from karazhan_tool.hashing import sha256_file
from karazhan_tool.review_pack import finding_ids

BLOCKING_STATUSES = ("rejected", "needs_change", "needs_evidence")

_CARD = """        <a class="report" href="reports/{date}/" style="animation-delay:0ms">
          <span class="day">{day}</span>
          <span>
            <span class="meta">{year} / {month} / 战斗报告</span>
            <span class="title">卡塔赞之塔战斗审计</span>
          </span>
          <span class="arrow" aria-hidden="true">→</span>
        </a>
"""


def check_gate(stage: Path) -> list[str]:
    """返回阻止发布的原因；空列表表示可以发布。"""
    problems: list[str] = []
    validation_path = stage / "validation.json"
    pack_path = stage / "review-pack.json"
    result_path = stage / "review-result.json"
    for path in (validation_path, pack_path, stage / "site" / "data.json"):
        if not path.is_file():
            problems.append(f"缺少 {path.name}")
    if problems:
        return problems
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if not validation.get("ok"):
        problems.append("自动校验未通过：" + "、".join(validation.get("failed", [])))
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    site_hash = "sha256:" + sha256_file(stage / "site" / "data.json")
    if pack.get("input_hashes", {}).get("display") != site_hash:
        problems.append("网站数据与复核包不是同一次运行")
    if not result_path.is_file():
        problems.append("缺少 AI 复核结果 review-result.json")
        return problems
    result = json.loads(result_path.read_text(encoding="utf-8"))
    expected = "sha256:" + sha256_file(pack_path)
    if (result.get("input_hashes") or {}).get("review_pack") != expected:
        problems.append("复核结果对应的证据包哈希与当前不一致，需重新复核")
    if result.get("status") != "approved":
        problems.append(f"复核状态为 {result.get('status')}")
    blocking = [
        item.get("finding_id") for item in result.get("items", [])
        if item.get("status") in BLOCKING_STATUSES
    ]
    if blocking:
        problems.append("仍有未通过的复核项：" + "、".join(str(item) for item in blocking[:10]))
    reviewed = {item.get("finding_id") for item in result.get("items", [])}
    unreviewed = [finding_id for finding_id in finding_ids(pack) if finding_id not in reviewed]
    if unreviewed:
        problems.append(f"复核包中有 {len(unreviewed)} 条未复核")
    if result.get("global_issues"):
        problems.append("仍有未处理的全局问题")
    return problems


def publish(stage: Path, site_root: Path, date: str, template: Path) -> list[Path]:
    report_dir = site_root / "reports" / date
    report_dir.mkdir(parents=True, exist_ok=True)
    written = []
    data_path = report_dir / "data.json"
    data_path.write_bytes((stage / "site" / "data.json").read_bytes())
    written.append(data_path)
    page = report_dir / "index.html"
    if not page.is_file():
        page.write_bytes(template.read_bytes())
        written.append(page)
    home = site_root / "index.html"
    text = home.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    updated = add_home_card(text.replace("\r\n", "\n"), date).replace("\n", newline)
    if updated != text:
        home.write_bytes(updated.encode("utf-8"))
        written.append(home)
    return written


def add_home_card(html: str, date: str) -> str:
    if f'href="reports/{date}/"' in html:
        return html
    year, month, day = date.split("-")
    marker = '<div class="reports">\n'
    if marker not in html:
        raise ValueError("首页缺少日期列表容器")
    card = _CARD.format(date=date, day=day, year=year, month=month)
    position = html.index(marker) + len(marker)
    for match in re.finditer(r'        <a class="report" href="reports/(\d{4}-\d{2}-\d{2})/"', html):
        if match.start() >= position and match.group(1) < date:
            position = match.start()
            break
    else:
        closing = html.find("      </div>", position)
        position = closing if closing >= 0 else position
    html = html[:position] + card + html[position:]
    delays = iter(range(0, 10_000, 70))
    html = re.sub(r'style="animation-delay:\d+ms"', lambda _: f'style="animation-delay:{next(delays)}ms"', html)
    count = html.count('class="report" href="reports/')
    return re.sub(r"共 \d+ 份报告", f"共 {count} 份报告", html, count=1)
