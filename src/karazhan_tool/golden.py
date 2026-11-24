"""从现有分析 JSON 抽出黄金指标，供以后逐项对比。"""

from __future__ import annotations

import json
from pathlib import Path

from karazhan_tool.hashing import canonical_sha256


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_metrics(analysis: dict) -> dict:
    metadata = analysis["metadata"]
    roles = [
        {"name": item["name"], "class": item["class"], "role": item["role"]}
        for item in analysis.get("roles", [])
    ]
    dps = analysis.get("dps", {})
    dps_players = [
        {
            "name": item["name"],
            "class": item.get("class"),
            "group": item.get("group"),
            "damage": item.get("damage"),
            "dps": item.get("dps"),
        }
        for item in dps.get("players", [])
    ]
    ranking = []
    zero_error = []
    for item in analysis.get("error_summary", {}).get("ranking", []):
        details = [
            {"issue": detail["issue"], "count": detail["count"]}
            for detail in item.get("details", [])
        ]
        entry = {"player": item["player"], "count": item["count"], "details": details}
        ranking.append(entry)
        if item["count"] == 0:
            zero_error.append(item["player"])
    wipes = []
    for item in analysis.get("error_summary", {}).get("wipe_causes", []):
        wipes.append(
            {
                "encounter": item.get("encounter"),
                "responsible": item.get("responsible"),
                "error": item.get("error"),
                "result": item.get("result"),
                "involved": list(item.get("involved") or []),
                "timeline": list(item.get("timeline") or []),
            }
        )
    bosses = []
    for name, body in analysis.get("boss_analysis", {}).items():
        preparation = []
        for item in body.get("preparation") or []:
            if isinstance(item, dict):
                preparation.append(
                    {
                        "item": item.get("item"),
                        "status": item.get("status"),
                        "missing_count": len(item.get("missing") or []),
                    }
                )
        bosses.append(
            {
                "boss": name,
                "sha256": canonical_sha256(body),
                "preparation": preparation,
            }
        )
    curses = []
    for encounter in analysis.get("curses", []):
        curses.append(
            {
                "boss": encounter.get("boss"),
                "curses": [
                    {
                        "curse": item.get("curse"),
                        "responsible": item.get("responsible"),
                        "is_error": item.get("is_error"),
                        "uptime_pct": item.get("uptime_pct"),
                    }
                    for item in encounter.get("curses", [])
                ],
            }
        )
    sections = {
        name: canonical_sha256(analysis[name])
        for name in (
            "roles",
            "dps",
            "buffs",
            "buff_coverage",
            "windfury_coverage",
            "curses",
            "dispel_candidates",
            "consumables",
            "boss_analysis",
            "error_summary",
        )
        if name in analysis
    }
    return {
        "schema_version": 1,
        "date": metadata["date"],
        "raid_start": metadata["raid_start"],
        "raid_end": metadata["raid_end"],
        "roster_size": metadata["roster_size"],
        "roster": list(metadata["roster"]),
        "role_counts": _count_roles(roles),
        "roles": roles,
        "dps": {
            "active_combat_time": dps.get("active_combat_time"),
            "elapsed_time": dps.get("elapsed_time"),
            "player_count": len(dps_players),
            "players": dps_players,
        },
        "error_ranking": ranking,
        "zero_error": zero_error,
        "wipe_causes": wipes,
        "bosses": bosses,
        "curses": curses,
        "section_sha256": sections,
    }


def _count_roles(roles: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in roles:
        role = item["role"]
        counts[role] = counts.get(role, 0) + 1
    return counts
