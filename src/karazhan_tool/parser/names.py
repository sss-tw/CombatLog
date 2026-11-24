"""按冻结名单解析姓名。

禁止先把“你”“你的”或“你的……”全局替换成记录者。第二人称和真实同名玩家同时保留为候选，
只有语法和名单能够唯一确定时才选定一名玩家。有 GUID 时以 GUID 为准。
"""

from __future__ import annotations

import re
from collections import defaultdict

from karazhan_tool.model import NameCandidate, NameResolution, Player

PET_SPELL_RE = re.compile(r"^(?P<pet>.+?) ?\((?P<owner>[^()]+)\)的(?P<spell>.+)$")
PET_MELEE_RE = re.compile(r"^(?P<pet>.+?) ?\((?P<owner>[^()]+)\)$")
PRONOUNS = ("你", "你自己")


class FrozenRoster:
    """解析开始后不可改写的玩家表。同一个 GUID 只对应一个显示名。"""

    def __init__(self, players: tuple[Player, ...] | list[Player], logger: Player | None):
        by_guid: dict[str, Player] = {}
        by_name: dict[str, list[Player]] = defaultdict(list)
        for player in players:
            if player.guid:
                previous = by_guid.get(player.guid)
                if previous is not None and previous.name != player.name:
                    raise ValueError(
                        f"GUID {player.guid} 不能同时对应 {previous.name} 和 {player.name}"
                    )
                by_guid[player.guid] = player
            by_name[player.name].append(player)
        self.players = tuple(players)
        self.logger = logger
        self.by_guid = by_guid
        self.by_name = {name: tuple(group) for name, group in by_name.items()}
        self.names_by_length = tuple(sorted(self.by_name, key=lambda name: (-len(name), name)))

    def players_named(self, name: str) -> tuple[Player, ...]:
        return self.by_name.get(name, ())


def normalize_guid(guid: str | None) -> str | None:
    if guid is None:
        return None
    text = guid.strip()
    if text.lower().startswith("0x"):
        return "0x" + text[2:].lower()
    return text


def resolve_unit_name(
    text: str,
    roster: FrozenRoster,
    *,
    guid: str | None = None,
) -> NameResolution:
    """解析死亡、光环持有者等纯单位字段。"""
    raw = text.strip()
    if guid:
        return _resolve_guid(raw, roster, guid, field="unit")
    exact = roster.players_named(raw)
    pronoun = _pronoun_unit(raw, roster)
    if exact or pronoun is not None:
        return _decide(raw, _player_candidates(exact, spell=None, pet=None) + _optional(pronoun))
    pet = _pet_parts(raw)
    if pet is not None and pet[2] is None and _known_owner(pet[1], roster):
        return _resolve_pet(raw, roster, pet[0], pet[1], None)
    return _unresolved(raw, "没有匹配到冻结名单中的完整姓名")


def resolve_source_prefix(
    text: str,
    roster: FrozenRoster,
    *,
    guid: str | None = None,
) -> NameResolution:
    """解析伤害或治疗来源前缀，区分玩家姓名、所有格和技能名。"""
    raw = text.strip()
    if guid:
        return _resolve_guid(raw, roster, guid, field="source")
    # 括号里必须是名单中的主人或第二人称，避免把技能后缀误判成宠物。
    if "(" in raw and not roster.players_named(raw):
        pet = _pet_parts(raw)
        if pet is not None and _known_owner(pet[1], roster):
            return _resolve_pet(raw, roster, pet[0], pet[1], pet[2])
    candidates: list[NameCandidate] = []
    matched = _longest_source(raw, roster)
    if matched is not None:
        name, spell = matched
        candidates.extend(_player_candidates(roster.players_named(name), spell, None))
    pronoun = _pronoun_source(raw, roster)
    if pronoun is not None:
        candidates.append(pronoun)
    if not candidates:
        return _unresolved(raw, "没有匹配到冻结名单中的完整姓名")
    return _decide(raw, candidates)


def _resolve_guid(raw: str, roster: FrozenRoster, guid: str, *, field: str) -> NameResolution:
    normalized = normalize_guid(guid)
    player = roster.by_guid.get(normalized or "")
    if player is None:
        return NameResolution(
            status="unresolved",
            method="guid",
            name=None,
            guid=normalized,
            spell=None,
            pet=None,
            candidates=(),
            flags=("unknown_guid",),
            confidence="low",
            raw=raw,
        )
    is_logger = _is_logger(player, roster)
    spell, pet, mismatch = _action_for_known_player(raw, player, is_logger, field)
    flags = ("guid_text_mismatch",) if mismatch else ()
    candidate = NameCandidate(
        kind="guid",
        name=player.name,
        guid=player.guid,
        spell=spell,
        pet=pet,
        reason="按 GUID 绑定冻结名单中的显示名",
    )
    return NameResolution(
        status="resolved",
        method="guid",
        name=player.name,
        guid=player.guid,
        spell=spell,
        pet=pet,
        candidates=(candidate,),
        flags=flags,
        confidence="medium" if mismatch else "high",
        raw=raw,
    )


def _action_for_known_player(
    raw: str,
    player: Player,
    is_logger: bool,
    field: str,
) -> tuple[str | None, str | None, bool]:
    pet = _pet_parts(raw)
    if pet is not None:
        pet_name, owner, spell = pet
        if owner == player.name or (is_logger and owner in PRONOUNS):
            return spell, pet_name, False
        return None, None, True
    if raw == player.name:
        return None, None, False
    owned = player.name + "的"
    if raw.startswith(owned) and len(raw) > len(owned):
        return raw[len(owned) :], None, False
    if field == "source" and is_logger and raw in PRONOUNS:
        return None, None, False
    if field == "unit" and is_logger and raw in PRONOUNS:
        return None, None, False
    if field == "source" and is_logger and raw.startswith("你的") and len(raw) > 2:
        return raw[2:], None, False
    if raw == "":
        return None, None, True
    return None, None, True


def _longest_source(raw: str, roster: FrozenRoster) -> tuple[str, str | None] | None:
    for name in roster.names_by_length:
        if raw == name:
            return name, None
        lead = name + "的"
        if raw.startswith(lead) and len(raw) > len(lead):
            return name, raw[len(lead) :]
    return None


def _pronoun_unit(raw: str, roster: FrozenRoster) -> NameCandidate | None:
    if raw not in PRONOUNS:
        return None
    return _logger_candidate(roster, spell=None, reason="单位字段是第二人称代词")


def _pronoun_source(raw: str, roster: FrozenRoster) -> NameCandidate | None:
    if raw in PRONOUNS:
        return _logger_candidate(roster, spell=None, reason="来源字段是第二人称代词")
    if raw.startswith("你的") and len(raw) > 2:
        return _logger_candidate(roster, spell=raw[2:], reason="来源字段是第二人称所有格加技能名")
    return None


def _logger_candidate(roster: FrozenRoster, *, spell: str | None, reason: str) -> NameCandidate:
    logger = roster.logger
    return NameCandidate(
        kind="logger_pronoun",
        name=None if logger is None else logger.name,
        guid=None if logger is None else logger.guid,
        spell=spell,
        pet=None,
        reason=reason,
    )


def _player_candidates(
    players: tuple[Player, ...],
    spell: str | None,
    pet: str | None,
) -> list[NameCandidate]:
    return [
        NameCandidate(
            kind="roster_name",
            name=player.name,
            guid=player.guid,
            spell=spell,
            pet=pet,
            reason="按冻结名单中的完整姓名最长匹配",
        )
        for player in players
    ]


def _pet_parts(raw: str) -> tuple[str, str, str | None] | None:
    matched = PET_SPELL_RE.fullmatch(raw)
    if matched:
        return matched.group("pet"), matched.group("owner"), matched.group("spell")
    matched = PET_MELEE_RE.fullmatch(raw)
    if matched:
        return matched.group("pet"), matched.group("owner"), None
    return None


def _resolve_pet(
    raw: str,
    roster: FrozenRoster,
    pet_name: str,
    owner_text: str,
    spell: str | None,
) -> NameResolution:
    owner = resolve_unit_name(owner_text, roster)
    if owner.status != "resolved":
        candidates = [
            NameCandidate(
                kind=item.kind,
                name=item.name,
                guid=item.guid,
                spell=spell,
                pet=pet_name,
                reason="宠物主人" + item.reason,
            )
            for item in owner.candidates
        ]
        flags = tuple(dict.fromkeys((*owner.flags, "ambiguous_name" if owner.status == "ambiguous" else "unresolved_owner")))
        return NameResolution(
            status=owner.status,
            method="ambiguous_name" if owner.status == "ambiguous" else "unresolved",
            name=None,
            guid=None,
            spell=spell,
            pet=pet_name,
            candidates=tuple(candidates),
            flags=flags,
            confidence="low",
            raw=raw,
        )
    candidate = NameCandidate(
        kind="pet_owner",
        name=owner.name,
        guid=owner.guid,
        spell=spell,
        pet=pet_name,
        reason="宠物伤害归主人，主人按冻结名单解析",
    )
    return NameResolution(
        status="resolved",
        method="pet_owner",
        name=owner.name,
        guid=owner.guid,
        spell=spell,
        pet=pet_name,
        candidates=(candidate,),
        flags=(),
        confidence="high",
        raw=raw,
    )


def _decide(raw: str, candidates: list[NameCandidate]) -> NameResolution:
    missing_logger = any(item.kind == "logger_pronoun" and item.name is None for item in candidates)
    usable = [item for item in candidates if item.name is not None]
    if not usable:
        reason = "第二人称没有对应的记录者身份" if missing_logger else "没有可用候选"
        flags = ("missing_logger_identity",) if missing_logger else ("unresolved_name",)
        return _unresolved(raw, reason, extra_flags=flags)
    unique: list[NameCandidate] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for item in usable:
        key = (item.guid or f"name:{item.name}", item.spell, item.pet)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda item: (item.name or "", item.spell or "", item.pet or "", item.kind))
    if len(unique) == 1 and not missing_logger:
        chosen = unique[0]
        return NameResolution(
            status="resolved",
            method=_resolved_method(chosen),
            name=chosen.name,
            guid=chosen.guid,
            spell=chosen.spell,
            pet=chosen.pet,
            candidates=(chosen,),
            flags=(),
            confidence="high",
            raw=raw,
        )
    flags = ["ambiguous_name"]
    if missing_logger:
        flags.append("missing_logger_identity")
    return NameResolution(
        status="ambiguous",
        method="ambiguous_name",
        name=None,
        guid=None,
        spell=None,
        pet=None,
        candidates=tuple(unique),
        flags=tuple(flags),
        confidence="low",
        raw=raw,
    )


def _resolved_method(candidate: NameCandidate) -> str:
    if candidate.kind == "logger_pronoun":
        return "logger_pronoun"
    if candidate.kind == "pet_owner":
        return "pet_owner"
    return "longest_name"


def _unresolved(raw: str, reason: str, extra_flags: tuple[str, ...] = ()) -> NameResolution:
    return NameResolution(
        status="unresolved",
        method="unresolved",
        name=None,
        guid=None,
        spell=None,
        pet=None,
        candidates=(
            NameCandidate(
                kind="unresolved",
                name=None,
                guid=None,
                spell=None,
                pet=None,
                reason=reason,
            ),
        ),
        flags=extra_flags or ("unresolved_name",),
        confidence="low",
        raw=raw,
    )


def _known_owner(owner: str, roster: FrozenRoster) -> bool:
    return owner in PRONOUNS or bool(roster.players_named(owner))


def _optional(candidate: NameCandidate | None) -> list[NameCandidate]:
    if candidate is None:
        return []
    return [candidate]


def _is_logger(player: Player, roster: FrozenRoster) -> bool:
    logger = roster.logger
    if logger is None:
        return False
    if player.guid and logger.guid:
        return player.guid == logger.guid
    return player.name == logger.name
