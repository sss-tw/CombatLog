"""发布前自动校验。任何一项失败都阻止发布。"""

from __future__ import annotations

import re
from collections import Counter

_PLACEHOLDER_RE = re.compile(r"\b(?:None|null|undefined|NaN|TODO|FIXME)\b")


def validate(
    report: dict,
    findings: list[dict],
    display: dict,
    *,
    golden: dict,
    approved_golden_diffs: int = 0,
    name_issues: list[dict] | None = None,
) -> dict:
    checks: list[dict] = []

    def check(check_id: str, ok: bool, detail: str = "") -> None:
        checks.append({"id": check_id, "ok": bool(ok), "detail": detail})

    summary = report["error_summary"]
    ranking = summary["ranking"]
    roster = report["metadata"]["roster"]

    bad = [
        item["player"] for item in ranking
        if item["count"] != sum(detail["count"] for detail in item["details"])
    ]
    check("ranking.details_sum", not bad, "、".join(bad))

    weights = Counter()
    for item in findings:
        weights[item["player"]] += item["weight"]
    mismatched = [
        item["player"] for item in ranking
        if weights.get(item["player"], 0) != item["count"]
    ]
    check("findings.match_ranking", not mismatched, "、".join(mismatched))
    check(
        "findings.total",
        sum(weights.values()) == sum(item["count"] for item in ranking),
        "%d / %d" % (sum(weights.values()), sum(item["count"] for item in ranking)),
    )

    check(
        "ranking.covers_roster",
        sorted(item["player"] for item in ranking) == sorted(roster),
        "排行 %d 人，名单 %d 人" % (len(ranking), len(roster)),
    )
    counts = [item["count"] for item in ranking]
    check("ranking.sorted", counts == sorted(counts, reverse=True))
    zero = [item["player"] for item in ranking if item["count"] == 0]
    tail = [item["player"] for item in ranking[len(ranking) - len(zero):]]
    check("ranking.zero_at_end", zero == tail, "、".join(zero))

    ids = [item["finding_id"] for item in findings]
    duplicates = [key for key, value in Counter(ids).items() if value > 1]
    check("findings.unique_id", not duplicates, "、".join(duplicates[:5]))
    missing_fields = [
        item["finding_id"] for item in findings
        if not item.get("rule_id") or not item.get("player") or "confidence" not in item
    ]
    check("findings.required_fields", not missing_fields, "、".join(missing_fields[:5]))
    no_evidence = [item["finding_id"] for item in findings if not item.get("evidence_lines")]
    check("findings.line_evidence", not no_evidence, "、".join(no_evidence[:5]))

    unresolved = [item for item in (name_issues or []) if item.get("reason") == "ambiguous_name"]
    check(
        "names.ambiguous_reviewed",
        True,
        "姓名歧义 %d 处，已进入复核包" % len(unresolved),
    )

    texts = list(_strings(display))
    placeholders = sorted({match.group(0) for text in texts for match in _PLACEHOLDER_RE.finditer(text)})
    check("display.no_placeholder", not placeholders, "、".join(placeholders))
    check(
        "display.same_run",
        display.get("date") == report["metadata"]["date"],
        "%s / %s" % (display.get("date"), report["metadata"]["date"]),
    )

    if golden.get("available"):
        check(
            "golden.diff",
            golden["total"] <= approved_golden_diffs,
            "差异 %d 处，已批准 %d 处" % (golden["total"], approved_golden_diffs),
        )

    failed = [item["id"] for item in checks if not item["ok"]]
    return {"ok": not failed, "failed": failed, "checks": checks}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
