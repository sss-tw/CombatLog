"""读取当周配置。玩家名、GUID 和路径只出现在配置里。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from karazhan_tool.timeutil import parse_clock, parse_timezone


@dataclass(frozen=True)
class RaidConfig:
    date: str
    timezone: str
    combat_log: Path
    raw_combat_log: Path
    custom_data: Path
    raid_start: str
    raid_end: str
    zone_names: tuple[str, ...]
    logger_guid: str
    logger_name: str
    roster_overrides: tuple[dict, ...]
    class_overrides: dict[str, str]
    declared_inputs: dict[str, str]
    input_notes: tuple[str, ...]
    golden_analysis: Path | None
    golden_display: Path | None
    golden_page: Path | None
    known_units: tuple[str, ...]
    source_path: Path
    raw: dict


def load_config(path: Path) -> RaidConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "date",
        "timezone",
        "combat_log",
        "raw_combat_log",
        "custom_data",
        "raid_start",
        "raid_end",
        "zone_names",
        "logger_identity",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError("日期配置缺少字段：" + "、".join(missing))
    logger = payload["logger_identity"]
    if not isinstance(logger, dict) or "guid" not in logger or "name" not in logger:
        raise ValueError("logger_identity 必须包含 guid 和 name")
    zones = payload["zone_names"]
    if not isinstance(zones, list) or not zones or not all(isinstance(item, str) for item in zones):
        raise ValueError("zone_names 必须是非空字符串数组")
    parse_timezone(payload["timezone"])
    parse_clock(payload["raid_start"])
    parse_clock(payload["raid_end"])
    base = path.parent
    golden = payload.get("golden_sources") or {}
    return RaidConfig(
        date=payload["date"],
        timezone=payload["timezone"],
        combat_log=_resolve(payload["combat_log"], base),
        raw_combat_log=_resolve(payload["raw_combat_log"], base),
        custom_data=_resolve(payload["custom_data"], base),
        raid_start=payload["raid_start"],
        raid_end=payload["raid_end"],
        zone_names=tuple(zones),
        logger_guid=logger["guid"],
        logger_name=logger["name"],
        roster_overrides=tuple(payload.get("roster_overrides") or ()),
        class_overrides=dict(payload.get("class_overrides") or {}),
        declared_inputs=dict(payload.get("declared_inputs") or {}),
        input_notes=tuple(payload.get("input_notes") or ()),
        golden_analysis=_optional_path(golden.get("analysis"), base),
        golden_display=_optional_path(golden.get("display"), base),
        golden_page=_optional_path(golden.get("page"), base),
        known_units=_known_units(payload),
        source_path=path,
        raw=payload,
    )


def _known_units(payload: dict) -> tuple[str, ...]:
    names: list[str] = []
    for item in payload.get("known_units") or []:
        if isinstance(item, str) and item and item not in names:
            names.append(item)
    for item in payload.get("encounters") or []:
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name and name not in names:
                names.append(name)
    return tuple(names)


def _resolve(value: str, base: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _optional_path(value: str | None, base: Path) -> Path | None:
    if not value:
        return None
    return _resolve(value, base)
