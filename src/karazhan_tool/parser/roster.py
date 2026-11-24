"""从 CustomData 和 RAW 日志冻结本场玩家名单。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from karazhan_tool.model import Player
from karazhan_tool.parser.names import FrozenRoster, normalize_guid
from karazhan_tool.timeutil import clock_to_epoch_ms, epoch_ms_to_local, log_month_day

CLASS_NAMES_ZH = {
    "WARRIOR": "战士",
    "PALADIN": "圣骑士",
    "HUNTER": "猎人",
    "ROGUE": "盗贼",
    "PRIEST": "牧师",
    "SHAMAN": "萨满",
    "MAGE": "法师",
    "WARLOCK": "术士",
    "DRUID": "德鲁伊",
}


class InputCoverageError(RuntimeError):
    """输入文件的时间范围盖不住当周战斗。"""


@dataclass(frozen=True)
class FreezeResult:
    roster: FrozenRoster
    warnings: tuple[str, ...]


@dataclass
class _Identity:
    guid: str
    name: str
    class_id: str | None
    names_seen: list[str] = field(default_factory=list)
    last_ts: int = 0


def freeze_roster(
    *,
    custom_data: Path,
    raw_combat_log: Path,
    date: str,
    timezone: str,
    raid_start: str,
    raid_end: str,
    zone_names: tuple[str, ...],
    logger_guid: str,
    logger_name: str,
    roster_overrides: tuple[dict, ...] = (),
    class_overrides: dict[str, str] | None = None,
    encounter_windows: tuple[tuple[str, str], ...] = (),
) -> FreezeResult:
    """先取当日 CustomData 身份，再用战斗时间内出现过的 GUID 确认参战。

    给了首领战时间窗时，只有在至少一场首领战里出现过的人才算参战。
    """
    day_start = clock_to_epoch_ms(date, "00:00:00.000", timezone)
    raid_start_ms = clock_to_epoch_ms(date, raid_start, timezone)
    raid_end_ms = clock_to_epoch_ms(date, raid_end, timezone)
    if raid_end_ms < raid_start_ms:
        raise ValueError("战斗结束时间早于开始时间")

    identities, header_guids, file_span, zones = _load_custom_data(
        custom_data,
        day_start,
        raid_end_ms,
    )
    if file_span[0] is None or file_span[1] is None:
        raise InputCoverageError(f"CustomData 没有任何时间戳：{custom_data}")
    if file_span[1] < day_start or file_span[0] > raid_end_ms:
        start_text = epoch_ms_to_local(file_span[0], timezone)
        end_text = epoch_ms_to_local(file_span[1], timezone)
        raise InputCoverageError(
            "CustomData 的时间范围盖不住本场战斗："
            f"{custom_data} 覆盖 {start_text[0]} {start_text[1]} 至 {end_text[0]} {end_text[1]}，"
            f"需要 {date} {raid_start} 至 {raid_end}"
        )

    warnings: list[str] = []
    seen_zones = {name for _ts, name in zones if name}
    missing_zones = [name for name in zone_names if name not in seen_zones]
    if missing_zones:
        warnings.append(
            "配置的副本名在当日截止时间前没有出现：" + "、".join(missing_zones)
        )

    logger_guid = normalize_guid(logger_guid) or ""
    if header_guids and logger_guid not in header_guids:
        warnings.append(
            "配置中的记录者 GUID 与 CustomData HEADER 不一致："
            + "、".join(sorted(header_guids))
        )

    windows = tuple(encounter_windows) or ((raid_start, raid_end),)
    active, raid_active, raw_window_has_events = _active_guids(
        raw_combat_log,
        log_month_day(date),
        raid_start,
        raid_end,
        windows,
        set(identities),
    )
    for guid in sorted(raid_active - active):
        identity = identities[guid]
        if guid != logger_guid:
            warnings.append(f"{identity.name} 只在首领战之外出现，没有参加任何一场首领战，未计入名单")
    excluded, included = _split_overrides(roster_overrides)
    class_overrides = class_overrides or {}
    players: list[Player] = []
    for guid, identity in identities.items():
        if guid in excluded or identity.name in excluded:
            continue
        # 记录者本人的原始日志写的是“你”，GUID 不会出现；时间窗里有事件即可确认其在场。
        logger_present = guid == logger_guid and raw_window_has_events
        if guid not in active and guid not in included and identity.name not in included and not logger_present:
            continue
        if len(set(identity.names_seen)) > 1:
            warnings.append(
                f"GUID {guid} 在冻结窗口内出现过多个名字："
                + "、".join(dict.fromkeys(identity.names_seen))
                + f"；采用截止前最后一次的 {identity.name}"
            )
        class_id = class_overrides.get(identity.name, identity.class_id)
        players.append(_make_player(guid, identity.name, class_id, ("custom_data", "raw_combat_log"), True))

    known = {player.guid for player in players}
    for item in roster_overrides:
        if item.get("action") != "include":
            continue
        guid = normalize_guid(item.get("guid"))
        name = item.get("name")
        if not name:
            raise ValueError("名单 include 覆盖必须写 name")
        if guid in known:
            continue
        class_id = item.get("class_id") or class_overrides.get(name)
        players.append(_make_player(guid, name, class_id, ("config",), True))
        known.add(guid)

    players.sort(key=lambda player: player.name)
    logger = _select_logger(players, logger_guid, logger_name, warnings)
    if logger is not None and logger.name != logger_name:
        warnings.append(
            f"记录者 GUID {logger.guid} 在 CustomData 中的名字是 {logger.name}，配置写的是 {logger_name}"
        )
    return FreezeResult(FrozenRoster(players, logger), tuple(warnings))


def roster_to_dict(roster: FrozenRoster, *, date: str, warnings: tuple[str, ...] | None = None) -> dict:
    stored = warnings if warnings is not None else ()
    return {
        "schema_version": 1,
        "date": date,
        "logger": None if roster.logger is None else roster.logger.to_dict(),
        "roster_size": len(roster.players),
        "players": [player.to_dict() for player in roster.players],
        "warnings": list(stored),
    }


def _make_player(
    guid: str | None,
    name: str,
    class_id: str | None,
    sources: tuple[str, ...],
    confirmed: bool,
) -> Player:
    return Player(
        guid=guid,
        name=name,
        class_id=class_id,
        class_name=CLASS_NAMES_ZH.get(class_id or "", class_id),
        sources=sources,
        confirmed=confirmed,
    )


def _select_logger(
    players: list[Player],
    logger_guid: str,
    logger_name: str,
    warnings: list[str],
) -> Player | None:
    for player in players:
        if player.guid == logger_guid:
            return player
    for player in players:
        if player.name == logger_name:
            warnings.append(f"记录者 {logger_name} 没有匹配到配置 GUID，已按姓名挂接")
            return player
    warnings.append(f"记录者 {logger_name}（{logger_guid}）不在冻结后的参战名单中")
    return None


def _split_overrides(overrides: tuple[dict, ...]) -> tuple[set[str], set[str]]:
    excluded: set[str] = set()
    included: set[str] = set()
    for item in overrides:
        action = item.get("action")
        guid = normalize_guid(item.get("guid"))
        name = item.get("name")
        target = included if action == "include" else excluded if action == "exclude" else None
        if target is None:
            raise ValueError(f"无法识别的名单覆盖动作：{action}")
        if guid:
            target.add(guid)
        if name:
            target.add(name)
    return excluded, included


def _load_custom_data(
    path: Path,
    start_ms: int,
    end_ms: int,
) -> tuple[dict[str, _Identity], set[str], tuple[int | None, int | None], list[tuple[int, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到 CustomData：{path}")
    identities: dict[str, _Identity] = {}
    header_guids: set[str] = set()
    zones: list[tuple[int, str]] = []
    minimum: int | None = None
    maximum: int | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            separator = line.find("|")
            if separator <= 0:
                continue
            head = line[:separator]
            if not head.isdigit():
                continue
            timestamp = int(head)
            rest = line[separator + 1 :]
            if rest.startswith("HEADER|"):
                parts = rest.rstrip("\n").split("|")
                if len(parts) >= 2:
                    guid = normalize_guid(parts[1])
                    if guid:
                        header_guids.add(guid)
                continue
            if timestamp <= 0:
                continue
            if minimum is None or timestamp < minimum:
                minimum = timestamp
            if maximum is None or timestamp > maximum:
                maximum = timestamp
            if timestamp < start_ms or timestamp > end_ms:
                continue
            if rest.startswith("ZONE_INFO|"):
                parts = rest.rstrip("\n").split("|")
                zones.append((timestamp, parts[1] if len(parts) > 1 else ""))
                continue
            if not rest.startswith("COMBATANT_INFO|"):
                continue
            parts = rest.rstrip("\n").split("|")
            if len(parts) < 4:
                continue
            guid = normalize_guid(parts[1])
            name = parts[2].strip()
            class_id = parts[3].strip() or None
            if not guid or not name:
                continue
            current = identities.get(guid)
            if current is None or timestamp >= current.last_ts:
                seen = [] if current is None else list(current.names_seen)
                seen.append(name)
                identities[guid] = _Identity(
                    guid=guid,
                    name=name,
                    class_id=class_id,
                    names_seen=seen,
                    last_ts=timestamp,
                )
    return identities, header_guids, (minimum, maximum), zones


def _active_guids(
    path: Path,
    month_day: str,
    raid_start: str,
    raid_end: str,
    windows: tuple[tuple[str, str], ...],
    watched: set[str],
) -> tuple[set[str], set[str], bool]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到 RAW 战斗日志：{path}")
    found: set[str] = set()
    raid_found: set[str] = set()
    saw_window = False
    prefix = month_day + " "
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith(prefix):
                continue
            clock = line[len(prefix) : len(prefix) + 12]
            if clock < raid_start or clock > raid_end:
                continue
            in_encounter = any(left <= clock <= right for left, right in windows)
            saw_window = saw_window or in_encounter
            start = 0
            while True:
                index = line.find("0x", start)
                if index < 0 or index + 2 >= len(line):
                    break
                end = index + 2
                while end < len(line) and line[end] in "0123456789abcdefABCDEF":
                    end += 1
                if end > index + 2:
                    guid = "0x" + line[index + 2 : end].lower()
                    if guid in watched:
                        raid_found.add(guid)
                        if in_encounter:
                            found.add(guid)
                start = end
    return found, raid_found, saw_window
