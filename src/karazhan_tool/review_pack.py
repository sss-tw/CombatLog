"""生成给 AI 的精简复核包。只放需要判断的条目和带行号的短证据。"""

from __future__ import annotations

import json
from pathlib import Path

from karazhan_tool.parser.evidence import read_many

_RAW_LIMIT = 160
_IMPACT_PLAYERS = 4


def build_review_pack(
    *,
    date: str,
    input_hashes: dict,
    report: dict,
    findings: list[dict],
    name_issues: list[dict],
    golden: dict,
    validation: dict,
    warnings: list[str],
    display_notes: dict,
    combat_log: Path,
) -> dict:
    selected: dict[str, tuple[dict, list[str]]] = {}

    def pick(item: dict, reason: str) -> None:
        entry = selected.setdefault(item["finding_id"], (item, []))
        if reason not in entry[1]:
            entry[1].append(reason)

    sampled_rules = set()
    for item in findings:
        if item["confidence"] != "high":
            pick(item, "置信度" + item["confidence"])
        if _high_impact(item):
            pick(item, "4人以上受影响或高额团伤")
        if item["weight"] > 1:
            pick(item, "权重大于1")
        if item["rule_id"] not in sampled_rules:
            sampled_rules.add(item["rule_id"])
            pick(item, "每条规则抽样1条")

    lines = sorted({
        evidence["line"]
        for item, _ in selected.values()
        for evidence in item.get("evidence_lines", [])
    })
    raw = read_many(combat_log, lines)
    groups: dict[str, dict] = {}
    for item, reasons in selected.values():
        group = groups.get(item["rule_id"])
        if group is None:
            group = groups[item["rule_id"]] = {
                "rule_id": item["rule_id"],
                "encounter_id": item.get("encounter_id"),
                "assumptions": item.get("assumptions") or [],
                "example": {
                    "finding_id": item["finding_id"],
                    "player": item["player"],
                    "weight": item["weight"],
                    "confidence": item["confidence"],
                    "review_reasons": reasons,
                    "values": _plain_values(item.get("values") or {}),
                    "evidence_lines": [
                        {
                            "line": evidence["line"],
                            "purpose": evidence["purpose"],
                            "raw": _clip(raw.get(evidence["line"], "")),
                        }
                        for evidence in item.get("evidence_lines", [])
                    ],
                },
                "others": [],
            }
            continue
        group["others"].append([
            item["finding_id"],
            item["player"],
            item["weight"],
            item["confidence"],
            "、".join(reasons),
            [evidence["line"] for evidence in item.get("evidence_lines", [])],
            _key_values(item.get("values") or {}),
        ])
    packed = [{key: value for key, value in group.items() if value not in (None, [])} for group in groups.values()]

    summary = report["error_summary"]
    ranking = summary["ranking"]
    return {
        "schema_version": 1,
        "date": date,
        "input_hashes": input_hashes,
        "summary": {
            "roster_size": report["metadata"]["roster_size"],
            "findings": len(findings),
            "selected_for_review": len(selected),
            "review_instruction": "每条规则先看 example 的原文证据；others 每行依次为 finding_id、玩家、权重、置信度、入选原因、证据行号、关键数值。需要原文时运行 evidence --finding <finding_id>。",
            "error_total": sum(item["count"] for item in ranking),
            "top_players": [
                {"player": item["player"], "count": item["count"]}
                for item in ranking[:5]
            ],
            "zero_error": [item["player"] for item in ranking if item["count"] == 0],
            "validation_ok": validation["ok"],
            "validation_failed": validation["failed"],
        },
        "encounters": [
            [prefix_id, window["start"], window["end"]]
            for prefix_id, window in sorted({
                item["encounter_id"]: item["window"]
                for item in findings if item.get("encounter_id") and item.get("window")
            }.items())
        ],
        "role_assignments": [
            [item["name"], item["class"], item["role"]]
            for item in report.get("roles", [])
        ],
        "findings": packed,
        "wipe_timelines": [
            {
                "encounter": item["encounter"],
                "responsible": item["responsible"],
                "error": item["error"],
                "result": item["result"],
                "involved_count": len(item.get("involved") or []),
                "deaths": len(item.get("deaths") or []),
                "timeline": [
                    "+%.1f %s" % (event["offset"], event["event"])
                    for event in (item.get("timeline") or [])
                ],
            }
            for item in summary.get("wipe_causes", [])
        ],
        "display_notes": display_notes,
        "name_issues": name_issues,
        "golden_diff": {
            "available": golden.get("available"),
            "total": golden.get("total"),
            "sections": golden.get("sections"),
            "samples": golden.get("samples", [])[:20],
        },
        "warnings": warnings,
    }


def _high_impact(item: dict) -> bool:
    values = item.get("values") or {}
    hit = values.get("hit_players")
    if isinstance(hit, int) and not isinstance(hit, bool) and hit >= _IMPACT_PLAYERS:
        return True
    damage = values.get("raid_damage") or values.get("raid_damage_075s")
    return isinstance(damage, (int, float)) and damage >= 20000


def dump_pack(path: Path, pack: dict) -> None:
    """顶层每个键一行，列表每项一行，既紧凑又便于按行号引用。"""
    parts = []
    for key, value in pack.items():
        if isinstance(value, list) and value:
            items = ",\n".join("  " + _compact(item) for item in value)
            parts.append(f' "{key}": [\n{items}\n ]')
        else:
            parts.append(f' "{key}": {_compact(value)}')
    path.write_text("{\n" + ",\n".join(parts) + "\n}\n", encoding="utf-8", newline="\n")


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def finding_ids(pack: dict) -> list[str]:
    ids = []
    for group in pack.get("findings", []):
        ids.append(group["example"]["finding_id"])
        ids.extend(row[0] for row in group.get("others", []))
    return ids


def _plain_values(values: dict) -> dict:
    return {
        key: value for key, value in values.items()
        if not (isinstance(value, str) and _is_clock(value))
    }


def _key_values(values: dict) -> dict:
    picked = {}
    for key, value in values.items():
        if isinstance(value, bool) or isinstance(value, str):
            continue
        if isinstance(value, (int, float)) and not key.endswith("offset") and key != "sec":
            picked[key] = value
        if len(picked) >= 4:
            break
    return picked


def _is_clock(text: str) -> bool:
    return len(text) == 12 and text[2] == ":" and text[5] == ":" and text[8] == "."


def _clip(text: str) -> str:
    return text if len(text) <= _RAW_LIMIT else text[:_RAW_LIMIT] + "…"
