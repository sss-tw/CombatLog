"""运行规则引擎，并给每条个人错误补上日志行证据。"""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass
from pathlib import Path

from karazhan_tool.config import RaidConfig
from karazhan_tool.parser.names import FrozenRoster
from karazhan_tool.rules import engine

_CLOCK_RE = re.compile(r"^\d\d:\d\d:\d\d\.\d{3}$")
_TIME_TOLERANCE = 0.06
_MAX_EVIDENCE = 4
_MAX_VALUES = 12


@dataclass(frozen=True)
class AnalysisResult:
    report: dict
    findings: list[dict]
    name_issues: list[dict]


def load_rules(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_settings(config: RaidConfig, roster: FrozenRoster, rules: dict) -> dict:
    analysis = config.raw.get("analysis") or {}
    anchor = analysis.get("custom_data_anchor") or {}
    missing = [key for key in ("epoch_ms", "log_time") if key not in anchor]
    if missing:
        raise ValueError("日期配置 analysis.custom_data_anchor 缺少：" + "、".join(missing))
    encounters = []
    attempts = {}
    extra_windows = []
    for item in config.raw.get("encounters") or []:
        encounters.append((item["name"], item["start"], item["end"]))
        boss_attempts = item.get("attempts") or [
            {"attempt": 1, "result": "击杀", "start": item["start"], "end": item["end"]}
        ]
        attempts[item["name"]] = boss_attempts
        extra_windows.extend(
            (attempt["start"], attempt["end"])
            for attempt in boss_attempts
            if attempt["result"] != "击杀"
        )
    if roster.logger is None:
        raise ValueError("规则引擎需要日志记录者身份")
    files = analysis.get("custom_data_files") or [str(config.custom_data)]
    table_path = rules.get("equipment_arcane_resistance")
    resist_table = (
        json.loads((Path(__file__).resolve().parents[2] / table_path).read_text(encoding="utf-8"))
        if table_path else {}
    )
    month, day = config.date.split("-")[1:]
    return {
        "date": config.date,
        "date_prefix": f"{int(month)}/{int(day)} ",
        "combat_log": str(config.combat_log),
        "gear_snapshot_file": analysis.get("gear_snapshot_file"),
        "custom_data_files": files,
        "arcane_resist_items": resist_table.get("items") or {},
        "arcane_resist_names": resist_table.get("names") or {},
        "anchor_epoch_ms": int(anchor["epoch_ms"]),
        "anchor_log_time": anchor["log_time"],
        "logger_name": roster.logger.name,
        "prep_start": analysis.get("prep_start"),
        "encounters": encounters,
        "extra_boss_windows": extra_windows,
        "attempts": attempts,
        "demon_slaying_bosses": rules.get("demon_slaying_bosses") or [],
        "wipe_causes": analysis.get("wipe_causes") or [],
        "known_units": list(config.raw.get("known_units") or []),
        "raid_start": config.raid_start,
        "raid_end": config.raid_end,
        "player_classes": {
            player.name: player.class_name or "未识别"
            for player in roster.players
        },
    }


def run_analysis(config: RaidConfig, roster: FrozenRoster, rules: dict) -> AnalysisResult:
    settings = build_settings(config, roster, rules)
    report, raw_findings, rows, name_issues = engine.analyze(settings)
    findings = attach_evidence(
        raw_findings,
        rows,
        encounters=settings["encounters"],
        logger=settings["logger_name"],
        prefixes=rules.get("boss_rule_prefix") or {},
        rule_keywords=rules.get("evidence_keywords") or {},
        attempts=settings["attempts"],
    )
    return AnalysisResult(report=report, findings=findings, name_issues=name_issues)


def attach_evidence(
    raw_findings: list[dict],
    rows: list[dict],
    *,
    encounters: list[tuple[str, str, str]],
    logger: str,
    prefixes: dict[str, str],
    rule_keywords: dict[str, list[str]] | None = None,
    attempts: dict[str, list[dict]] | None = None,
) -> list[dict]:
    secs = [row["sec"] for row in rows]
    windows = {name: (engine.seconds(start), engine.seconds(end)) for name, start, end in encounters}
    counters: dict[str, int] = {}
    findings = []
    for item in raw_findings:
        rule_id = "%s.%s" % (prefixes.get(item["boss"], "misc"), item["issue"])
        counters[rule_id] = counters.get(rule_id, 0) + 1
        window = _attempt_window(item, (attempts or {}).get(item["boss"]) or []) or windows.get(item["boss"])
        moments = _moments(item["sources"], window)
        aliases = _aliases(item["player"], logger)
        extra = tuple((rule_keywords or {}).get(rule_id, ()))
        evidence, confidence = _evidence_for(item, rows, secs, moments, aliases, window, extra)
        finding = {
            "finding_id": "%s.%03d" % (rule_id, counters[rule_id]),
            "rule_id": rule_id,
            "player": item["player"],
            "status": "error",
            "weight": item["weight"],
            "issue": "%s·%s" % (item["boss"], item["issue"]),
            "values": _values(item["sources"]),
            "evidence_lines": evidence,
            "confidence": confidence,
            "assumptions": _assumptions(item["sources"]),
        }
        if window is not None:
            finding["encounter_id"] = prefixes.get(item["boss"], "misc") + ".01"
            finding["window"] = {
                "start": engine.clock_label(window[0]),
                "end": engine.clock_label(window[1]),
            }
        findings.append(finding)
    return findings


def _attempt_window(item: dict, attempts: list[dict]) -> tuple[float, float] | None:
    for source in item["sources"]:
        if isinstance(source, dict) and isinstance(source.get("attempt"), int):
            for attempt in attempts:
                if attempt.get("attempt") == source["attempt"]:
                    return engine.seconds(attempt["start"]), engine.seconds(attempt["end"])
    return None


def _evidence_for(item, rows, secs, moments, aliases, window, extra_keywords=()):
    evidence: list[dict] = []
    seen: set[int] = set()

    def keep(row, purpose):
        if row is None or row["line"] in seen or len(evidence) >= _MAX_EVIDENCE:
            return
        seen.add(row["line"])
        evidence.append({"line": row["line"], "timestamp": row["ts"], "purpose": purpose})

    keywords = _keywords(item) + tuple(extra_keywords)
    for moment, purpose in moments:
        keep(_nearest_row(rows, secs, moment, aliases, keywords), _label(purpose))
    if evidence:
        return evidence, "high"
    for moment, purpose in moments[:2]:
        keep(_nearest_row(rows, secs, moment, (), keywords), _label(purpose) + "（机制事件）")
    if evidence:
        return evidence, "high"
    for moment, purpose in moments:
        keep(_nearest_row(rows, secs, moment, aliases, ()), _label(purpose) + "（同刻该玩家记录）")
    if evidence:
        return evidence, "medium"
    buff = _buff_rows(item["sources"], rows)
    if buff:
        keep(buff[0], "该增益在受影响玩家身上的首条记录")
        keep(buff[-1], "该增益在受影响玩家身上的末条记录")
        return evidence, "medium"
    if window is not None:
        index = bisect.bisect_left(secs, window[0])
        if index < len(rows):
            keep(rows[index], "开怪时刻")
        if "开打" in item["issue"]:
            return evidence, "high"
        row = _first_row(rows, secs, window, aliases)
        keep(row, "首领战内该玩家首条记录，仅用于定位")
        return evidence, "medium"
    return evidence, "low"


def _buff_rows(sources: list, rows: list[dict]) -> list[dict]:
    for source in sources:
        if not isinstance(source, dict) or "buff" not in source:
            continue
        names = list(source.get("affected") or []) + list(source.get("responsible") or [])
        buff = source["buff"]
        return [
            row for row in rows
            if buff in row["body"] and any(name in row["body"] for name in names)
        ]
    return []


def _aliases(player: str, logger: str) -> tuple[str, ...]:
    return (player, "你") if player == logger else (player,)


def _moments(sources: list, window: tuple[float, float] | None) -> list[tuple[float, str]]:
    moments: list[tuple[float, str]] = []
    for source in reversed(sources):
        _collect(source, window, moments, depth=0, key="")
    return moments


def _collect(value, window, moments, *, depth: int, key: str) -> None:
    if depth > 3:
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            _collect(child, window, moments, depth=depth + 1, key=child_key)
    elif isinstance(value, list):
        for child in value[:8]:
            _collect(child, window, moments, depth=depth + 1, key=key)
    elif isinstance(value, str) and _CLOCK_RE.match(value):
        moments.append((engine.seconds(value), key or "时间"))
    elif key == "sec" and isinstance(value, (int, float)) and not isinstance(value, bool):
        moments.append((float(value), "时间"))
    elif (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and window is not None
        and (key == "offset" or key.endswith("_offset"))
    ):
        moment = window[0] + float(value)
        if window[0] - 5.0 <= moment <= window[1] + 15.0:
            moments.append((moment, key))


_KEYWORD_FIELDS = (
    "spell", "name", "buff", "curse", "item", "log_aura", "removed", "mechanic",
    "owl", "interrupt_spell", "dispel", "dispel_spell", "late_taunt_spell", "affinity", "target",
)
_LABELS = {
    "ts": "时间", "sec": "时间", "offset": "发生时间", "first_cast": "首次施放",
    "start_offset": "开始", "end_offset": "结束", "applied_offset": "获得效果",
    "resolved_offset": "效果结算", "removed_offset": "效果移除", "death_offset": "死亡",
    "spawn_offset": "出现", "first_offset": "首次出现或首次攻击", "first_attack_offset": "首次攻击",
    "allowed_until_offset": "允许攻击截止", "interrupt_offset": "打断", "feedback_offset": "裂隙回馈",
    "dispel_offset": "驱散", "cast_offset": "开始施放", "observed_offset": "首次出现",
    "damage_offset": "受到伤害", "late_taunt_offset": "嘲讽", "suppression_offset": "效果消失",
    "first_soak_offset": "首次踩圈", "expired": "效果消失", "regained": "重新获得",
    "boss_start": "开怪", "window_end_offset": "检查窗口结束", "mana_drain_start_offset": "开始吸蓝",
    "mana_drain_hit_offset": "吸蓝命中",
}


def _label(key: str) -> str:
    return _LABELS.get(key, key)


_ISSUE_KEYWORD_RES = (
    re.compile(r"(?:开打未保持|开打缺少|开打未吃|死于|错误解除|错误打断)(.+)$"),
    re.compile(r"^(.+?)(?:到期未及时补|有断档|断档|打断过早)$"),
)


def _keywords(item: dict) -> tuple[str, ...]:
    words = []
    for pattern in _ISSUE_KEYWORD_RES:
        match = pattern.search(item["issue"])
        if match and len(match.group(1)) >= 2:
            words.append(match.group(1))
    for source in item["sources"]:
        if not isinstance(source, dict):
            continue
        for key in _KEYWORD_FIELDS:
            value = source.get(key)
            if isinstance(value, str) and 2 <= len(value) <= 20 and value not in words and value != item["player"]:
                words.append(value)
    return tuple(words)


def _nearest_row(rows, secs, moment, aliases, keywords=()):
    left = bisect.bisect_left(secs, moment - _TIME_TOLERANCE)
    right = bisect.bisect_right(secs, moment + _TIME_TOLERANCE)
    best = None
    for index in range(left, right):
        body = rows[index]["body"]
        if keywords and not any(word in body for word in keywords):
            continue
        if not aliases or any(name in body for name in aliases):
            distance = abs(rows[index]["sec"] - moment)
            if best is None or distance < best[0]:
                best = (distance, rows[index])
    return None if best is None else best[1]


def _first_row(rows, secs, window, aliases):
    left = bisect.bisect_left(secs, window[0])
    right = bisect.bisect_right(secs, window[1])
    for index in range(left, right):
        if any(name in rows[index]["body"] for name in aliases):
            return rows[index]
    return None


def _values(sources: list) -> dict:
    values: dict = {}
    for source in reversed(sources):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if len(values) >= _MAX_VALUES:
                return values
            if key in values:
                continue
            if isinstance(value, (int, float, bool)) or (isinstance(value, str) and len(value) <= 40):
                values[key] = value
    return values


def _assumptions(sources: list) -> list[str]:
    notes = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("error_rule", "rule", "note", "reason"):
            text = source.get(key)
            if isinstance(text, str) and text and text not in notes:
                notes.append(text)
    return notes


def normalize_unordered(payload, paths: list[str]):
    """把黄金对比中无序的列表排序，避免集合遍历顺序造成假差异。"""
    for path in paths:
        parts = path[2:].split(".")
        _sort_path(payload, parts)
    return payload


def _sort_path(node, parts: list[str]) -> None:
    if not parts:
        return
    head = parts[0]
    is_list = head.endswith("[]")
    key = head[:-2] if is_list else head
    if not isinstance(node, dict) or key not in node:
        return
    child = node[key]
    if len(parts) == 1:
        if isinstance(child, list):
            node[key] = sorted(child, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))
        return
    if is_list and isinstance(child, list):
        for item in child:
            _sort_path(item, parts[1:])
    else:
        _sort_path(child, parts[1:])
