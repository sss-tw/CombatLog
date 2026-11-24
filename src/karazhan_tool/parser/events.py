"""把中文战斗日志解析成结构化事件。

批量结果不保存整行原文。行号指向原始日志，需要复核时再按行取出。
无法唯一确定的姓名会带上候选，不把“你/你的”先替换成记录者。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from karazhan_tool.parser.names import (
    FrozenRoster,
    NameResolution,
    resolve_source_prefix,
    resolve_unit_name,
)
from karazhan_tool.timeutil import log_month_day, parse_clock

SCHOOLS = "物理|火焰|冰霜|奥术|暗影|自然|神圣"
POWERS = "法力值|能量|怒气|集中值"
LINE_RE = re.compile(r"^(\d{1,2}/\d{1,2}) (\d\d:\d\d:\d\d\.\d{3})\s+(.*)$")
TAIL_RE = re.compile(r"[（(](\d+)点被(吸收|抵抗|格挡)[）)]")
SCHOOL_RE = re.compile(rf"(?P<school>{SCHOOLS})伤害")


@dataclass(frozen=True)
class CombatEvent:
    line: int
    timestamp: str
    seconds: float
    type: str
    source: str | None = None
    source_guid: str | None = None
    source_resolution: str | None = None
    target: str | None = None
    target_guid: str | None = None
    target_resolution: str | None = None
    spell: str | None = None
    school: str | None = None
    power: str | None = None
    amount: int | None = None
    absorbed: int | None = None
    resisted: int | None = None
    blocked: int | None = None
    stacks: int | None = None
    miss: str | None = None
    critical: bool = False
    pet: str | None = None
    target_pet: str | None = None
    flags: tuple[str, ...] = ()
    candidates: tuple[dict, ...] = ()
    text: str | None = None

    def located(self, line: int, timestamp: str) -> CombatEvent:
        return CombatEvent(
            line=line,
            timestamp=timestamp,
            seconds=parse_clock(timestamp),
            type=self.type,
            source=self.source,
            source_guid=self.source_guid,
            source_resolution=self.source_resolution,
            target=self.target,
            target_guid=self.target_guid,
            target_resolution=self.target_resolution,
            spell=self.spell,
            school=self.school,
            power=self.power,
            amount=self.amount,
            absorbed=self.absorbed,
            resisted=self.resisted,
            blocked=self.blocked,
            stacks=self.stacks,
            miss=self.miss,
            critical=self.critical,
            pet=self.pet,
            target_pet=self.target_pet,
            flags=self.flags,
            candidates=self.candidates,
            text=self.text,
        )

    def to_dict(self) -> dict:
        data = {
            "line": self.line,
            "timestamp": self.timestamp,
            "seconds": self.seconds,
            "type": self.type,
        }
        fields = {
            "source": self.source,
            "source_guid": self.source_guid,
            "source_resolution": self.source_resolution,
            "target": self.target,
            "target_guid": self.target_guid,
            "target_resolution": self.target_resolution,
            "spell": self.spell,
            "school": self.school,
            "power": self.power,
            "amount": self.amount,
            "absorbed": self.absorbed,
            "resisted": self.resisted,
            "blocked": self.blocked,
            "stacks": self.stacks,
            "miss": self.miss,
            "pet": self.pet,
            "target_pet": self.target_pet,
            "text": self.text,
        }
        for key, value in fields.items():
            if value is not None and value != "":
                data[key] = value
        if self.critical:
            data["critical"] = True
        if self.flags:
            data["flags"] = list(self.flags)
        if self.candidates:
            data["candidates"] = list(self.candidates)
        return data


@dataclass(frozen=True)
class _Actor:
    name: str | None
    guid: str | None
    resolution: str
    spell: str | None
    pet: str | None
    flags: tuple[str, ...]
    candidates: tuple[dict, ...]
    raw: str


def parse_body(
    body: str,
    roster: FrozenRoster,
    *,
    known_units: tuple[str, ...] = (),
) -> CombatEvent:
    """解析一条日志正文。调用方再补上行号和时间。"""
    text = body.strip()
    parsed = _parse_clause(text, roster, known_units)
    if parsed is not None:
        return parsed
    return CombatEvent(0, "", 0.0, "UNPARSED", text=text)


def iter_events(
    path,
    roster: FrozenRoster,
    *,
    date: str,
    start: str,
    end: str,
    known_units: tuple[str, ...] = (),
) -> Iterator[CombatEvent]:
    month_day = log_month_day(date)
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            matched = LINE_RE.match(line.rstrip("\n"))
            if matched is None or matched.group(1) != month_day:
                continue
            clock = matched.group(2)
            if clock < start or clock > end:
                continue
            yield parse_body(matched.group(3), roster, known_units=known_units).located(number, clock)


def summarize(events: Iterator[CombatEvent], roster: FrozenRoster, *, example_limit: int = 12) -> dict:
    counts: Counter[str] = Counter()
    ambiguous = 0
    unparsed = 0
    templates: Counter[str] = Counter()
    unparsed_examples: list[dict] = []
    ambiguous_examples: list[dict] = []
    total = 0
    for event in events:
        total += 1
        counts[event.type] += 1
        if "ambiguous_name" in event.flags:
            ambiguous += 1
            if len(ambiguous_examples) < example_limit:
                ambiguous_examples.append(event.to_dict())
        if event.type == "UNPARSED":
            unparsed += 1
            key = _template(event.text or "", roster)
            templates[key] += 1
            if len(unparsed_examples) < example_limit:
                unparsed_examples.append(
                    {"line": event.line, "timestamp": event.timestamp, "text": event.text}
                )
    return {
        "events": total,
        "by_type": dict(counts.most_common()),
        "ambiguous_names": ambiguous,
        "unparsed": unparsed,
        "unparsed_templates": [
            {"count": count, "template": template}
            for template, count in templates.most_common(example_limit)
        ],
        "unparsed_examples": unparsed_examples,
        "ambiguous_examples": ambiguous_examples,
    }


def _parse_clause(text: str, roster: FrozenRoster, known_units: tuple[str, ...]) -> CombatEvent | None:
    swing = re.fullmatch(
        r"(.+?)发起了攻击。(?:(.+?)(招架住了|闪躲开了|躲闪了|格挡住了)。)?",
        text,
    )
    if swing:
        source = _unit(swing.group(1), roster)
        how = swing.group(3)
        target = _unit(swing.group(2), roster) if swing.group(2) else None
        return _event(
            "MISS" if target else "SWING",
            source,
            target,
            spell="近战",
            miss=_miss_name(how) if how else None,
        )

    swing_immune = re.fullmatch(r"(.+?)发起了攻击，但是(.+?)对此免疫。?", text)
    if swing_immune:
        return _event(
            "MISS",
            _unit(swing_immune.group(1), roster),
            _unit(swing_immune.group(2), roster),
            spell="近战",
            miss="免疫",
        )

    immune = re.fullmatch(r"(.+?)施放失败。(.+?)对此免疫。?", text)
    if immune:
        source = _prefix(immune.group(1), roster, known_units, possessive=True)
        target = _unit(immune.group(2), roster)
        return _event("CAST_FAIL", source, target, spell=source.spell, miss="免疫")

    failed = re.fullmatch(r"(.+?)施放(.+?)失败：(.+)", text)
    if failed:
        source = _unit(failed.group(1), roster)
        reason = failed.group(3).strip()
        miss = "被打断" if reason == "被打断" else None
        return _event(
            "CAST_FAIL",
            source,
            None,
            spell=failed.group(2),
            miss=miss or reason,
        )

    interrupted = re.fullmatch(r"(.+?)打断了(.+)。?", text)
    if interrupted:
        source = _unit(interrupted.group(1), roster)
        target = _prefix(interrupted.group(2), roster, known_units, possessive=True)
        return _event("INTERRUPT", source, target, spell=target.spell)

    resisted = re.fullmatch(r"(.+?)被(.+?)(抵抗了|招架了|闪躲过去|闪避过去|躲闪了|格挡了|格挡住了)。?", text)
    if resisted:
        source = _prefix(resisted.group(1), roster, known_units, possessive=True)
        target = _unit(resisted.group(2), roster)
        return _event("MISS", source, target, spell=source.spell, miss=_miss_name(resisted.group(3)))

    missed = re.fullmatch(r"(.+?)没有击中(.+)。?", text)
    if missed:
        return _event(
            "MISS",
            _prefix(missed.group(1), roster, known_units, possessive=True),
            _unit(missed.group(2), roster),
            spell="近战",
            miss="未命中",
        )

    immune_to = re.fullmatch(r"(.+?)对(.+)免疫。?", text)
    if immune_to:
        affected = _prefix(immune_to.group(2), roster, known_units, possessive=True)
        return _event(
            "MISS",
            _unit(immune_to.group(1), roster),
            affected,
            spell=affected.spell,
            miss="免疫",
        )

    reflected = re.fullmatch(rf"(.+?)将(\d+)点({SCHOOLS})伤害反射给(.+)。?", text)
    if reflected:
        source = _unit(reflected.group(1), roster)
        target = _unit(reflected.group(4), roster)
        return _event(
            "REFLECT",
            source,
            target,
            school=reflected.group(3),
            amount=int(reflected.group(2)),
        )

    extra = re.fullmatch(r"(.+?)通过(.+?)获得了(\d+)次额外攻击。?", text)
    if extra:
        source = _unit(extra.group(1), roster)
        return _event("EXTRA_ATTACK", source, None, spell=extra.group(2), amount=int(extra.group(3)))

    drained = re.fullmatch(rf"(.+?)从(.+?)身上吸取了(\d+)点({POWERS})。?", text)
    if drained:
        source = _prefix(drained.group(1), roster, known_units, possessive=True)
        target = _unit(drained.group(2), roster)
        return _event(
            "DRAIN",
            source,
            target,
            spell=source.spell,
            power=drained.group(4),
            amount=int(drained.group(3)),
        )

    hit = re.fullmatch(
        rf"(.+?)(?:致命一击对|击中|对)(.+?)造成了?(\d+)(?:点(?:致命一击)?(?:({SCHOOLS}))?伤害|的致命一击)(.*)",
        text,
    )
    if hit and "恢复了" not in text:
        source = _prefix(hit.group(1), roster, known_units, possessive=True)
        target = _unit(hit.group(2), roster)
        absorbed, resisted_amount, blocked = _tail(hit.group(5) or "")
        return _event(
            "DAMAGE",
            source,
            target,
            spell=source.spell,
            school=hit.group(4) or _school(text),
            amount=int(hit.group(3)),
            absorbed=absorbed,
            resisted=resisted_amount,
            blocked=blocked,
            critical="致命一击对" in text or "点致命一击" in text or "的致命一击" in text,
            pet=source.pet,
        )

    dot = re.fullmatch(rf"(.+?)使(.+?)受到了(\d+)点(?:({SCHOOLS}))?伤害(.*)", text)
    if dot:
        source = _prefix(dot.group(1), roster, known_units, possessive=True)
        target = _unit(dot.group(2), roster)
        absorbed, resisted_amount, blocked = _tail(dot.group(5) or "")
        return _event(
            "DAMAGE",
            source,
            target,
            spell=source.spell,
            school=dot.group(4) or _school(text),
            amount=int(dot.group(3)),
            absorbed=absorbed,
            resisted=resisted_amount,
            blocked=blocked,
            pet=source.pet,
        )

    suffered = re.fullmatch(rf"(.+?)受到了(\d+)点(?:({SCHOOLS}))?伤害(.*)", text)
    if suffered:
        target = _unit(suffered.group(1), roster)
        absorbed, resisted_amount, blocked = _tail(suffered.group(4) or "")
        return _event(
            "DAMAGE",
            None,
            target,
            school=suffered.group(3) or _school(text),
            amount=int(suffered.group(2)),
            absorbed=absorbed,
            resisted=resisted_amount,
            blocked=blocked,
        )

    heal = re.fullmatch(r"(.+?)(?:发挥极效，)?为(.+?)恢复了(\d+)点生命值。?(.*)", text)
    if heal:
        source = _prefix(heal.group(1), roster, known_units, possessive=True)
        target = _unit(heal.group(2), roster)
        return _event(
            "HEAL",
            source,
            target,
            spell=source.spell,
            amount=int(heal.group(3)),
            critical="发挥极效" in text,
            pet=source.pet,
        )

    periodic = re.fullmatch(r"(.+?)获得了?(\d+)点生命值（(.+)）。?", text)
    if periodic:
        target = _unit(periodic.group(1), roster)
        source = _prefix(periodic.group(3), roster, known_units, possessive=True)
        return _event("HEAL", source, target, spell=source.spell, amount=int(periodic.group(2)), pet=source.pet)

    caused = re.fullmatch(r"(.+?)因(.+?)而获得了(\d+)点生命值。?", text)
    if caused:
        target = _unit(caused.group(1), roster)
        source = _prefix(caused.group(2), roster, known_units, possessive=True)
        return _event("HEAL", source, target, spell=source.spell, amount=int(caused.group(3)), pet=source.pet)

    treated = re.fullmatch(r"(.+?)治疗了(.+?)(\d+)点生命值。?", text)
    if treated:
        source = _prefix(treated.group(1), roster, known_units, possessive=True)
        target = _unit(treated.group(2), roster)
        return _event("HEAL", source, target, spell=source.spell, amount=int(treated.group(3)), pet=source.pet)

    aura_hit = re.fullmatch(rf"(.+?)受到(\d+)点(?:({SCHOOLS}))?伤害（(.+)）。?", text)
    if aura_hit:
        target = _unit(aura_hit.group(1), roster)
        source = _prefix(aura_hit.group(4), roster, known_units, possessive=True)
        return _event(
            "DAMAGE",
            source,
            target,
            spell=source.spell,
            school=aura_hit.group(3) or _school(text),
            amount=int(aura_hit.group(2)),
            pet=source.pet,
        )

    energize = re.fullmatch(rf"(.+?)从(.+?)获得了(\d+)点({POWERS})。?", text)
    if energize and "身上吸取了" not in text:
        target = _unit(energize.group(1), roster)
        source = _prefix(energize.group(2), roster, known_units, possessive=True)
        return _event(
            "ENERGIZE",
            source,
            target,
            spell=source.spell,
            power=energize.group(4),
            amount=int(energize.group(3)),
            pet=source.pet,
        )

    gained_power = re.fullmatch(rf"(.+?)获得了(\d+)点({POWERS})。?", text)
    if gained_power:
        target = _unit(gained_power.group(1), roster)
        return _event(
            "ENERGIZE",
            None,
            target,
            power=gained_power.group(3),
            amount=int(gained_power.group(2)),
        )

    removed = re.fullmatch(r"(.+?)被(?:(.+?))?移除了。?", text)
    if removed:
        source = _prefix(removed.group(1), roster, known_units, possessive=True)
        dispeller = _unit(removed.group(2), roster) if removed.group(2) else None
        return _event("AURA_REMOVED", dispeller, source, spell=source.spell)

    failed_plain = re.fullmatch(r"(.+?)施放失败了?。?", text)
    if failed_plain:
        source = _prefix(failed_plain.group(1), roster, known_units, possessive=True)
        return _event("CAST_FAIL", source, None, spell=source.spell)

    fade = re.fullmatch(r"(.+?)效果从(.+?)身上消失了?。?", text)
    if fade:
        target = _unit(fade.group(2), roster)
        return _event("AURA_FADE", None, target, spell=fade.group(1))

    gain = re.fullmatch(r"(.+?)获得了(.+?)的效果(?:（(\d+)）)?。?", text)
    if gain:
        target = _unit(gain.group(1), roster)
        stacks = int(gain.group(3)) if gain.group(3) else None
        return _event("AURA_GAIN", None, target, spell=gain.group(2), stacks=stacks)

    suffer = re.fullmatch(r"(.+?)受到了(.+?)效果(?:的影响)?(?:（(\d+)）)?。?", text)
    if suffer and not suffer.group(2)[:1].isdigit():
        target = _unit(suffer.group(1), roster)
        stacks = int(suffer.group(3)) if suffer.group(3) else None
        return _event("AURA_GAIN", None, target, spell=suffer.group(2), stacks=stacks)

    cast_at = re.fullmatch(r"(.+?)对(.+?)施放了(.+)。?", text)
    if cast_at:
        source = _unit(cast_at.group(1), roster)
        target = _unit(cast_at.group(2), roster)
        return _event("CAST_SUCCESS", source, target, spell=cast_at.group(3))

    used = re.fullmatch(r"(.+?)对(.+?)使用(.+)。?", text)
    if used:
        return _event(
            "CAST_SUCCESS",
            _unit(used.group(1), roster),
            _unit(used.group(2), roster),
            spell=used.group(3),
        )

    used_self = re.fullmatch(r"(.+?)使用(.+)。?", text)
    if used_self:
        return _event("CAST_SUCCESS", _unit(used_self.group(1), roster), None, spell=used_self.group(2))

    started = re.fullmatch(r"(.+?)开始施放(.+)。?", text)
    if started:
        source = _unit(started.group(1), roster)
        return _event("CAST_START", source, None, spell=started.group(2))

    cast = re.fullmatch(r"(.+?)施放了(.+)。?", text)
    if cast:
        source = _unit(cast.group(1), roster)
        return _event("CAST_SUCCESS", source, None, spell=cast.group(2))

    falling = re.fullmatch(r"(.+?)从高处掉落损失(\d+)生命值。?", text)
    if falling:
        return _event("DAMAGE", None, _unit(falling.group(1), roster), spell="高处掉落", school="物理", amount=int(falling.group(2)))

    death = re.fullmatch(r"(.+?)死亡了。?", text)
    if death:
        return _event("DEATH", None, _unit(death.group(1), roster))

    crafted = re.fullmatch(r"(.+?)制造了(.+)。?", text)
    if crafted:
        return _event("CRAFT", _unit(crafted.group(1), roster), None, spell=crafted.group(2))

    vanished = re.fullmatch(r"(.+?)消失了?。?", text)
    if vanished and "效果从" not in text:
        return _event("VANISH", None, _unit(vanished.group(1), roster))

    return None


def _event(
    event_type: str,
    source: _Actor | None,
    target: _Actor | None,
    *,
    spell: str | None = None,
    school: str | None = None,
    power: str | None = None,
    amount: int | None = None,
    absorbed: int | None = None,
    resisted: int | None = None,
    blocked: int | None = None,
    stacks: int | None = None,
    miss: str | None = None,
    critical: bool = False,
    pet: str | None = None,
) -> CombatEvent:
    flags: list[str] = []
    candidates: list[dict] = []
    for field, actor in (("source", source), ("target", target)):
        if actor is None:
            continue
        flags.extend(actor.flags)
        for candidate in actor.candidates:
            item = dict(candidate)
            item["field"] = field
            candidates.append(item)
    chosen_spell = spell
    source_pet = pet or (None if source is None else source.pet)
    target_pet = None if target is None else target.pet
    if chosen_spell:
        chosen_spell = chosen_spell.rstrip("。.")
    return CombatEvent(
        0,
        "",
        0.0,
        event_type,
        source=None if source is None else source.name,
        source_guid=None if source is None else source.guid,
        source_resolution=None if source is None else source.resolution,
        target=None if target is None else target.name,
        target_guid=None if target is None else target.guid,
        target_resolution=None if target is None else target.resolution,
        spell=chosen_spell,
        school=school,
        power=power,
        amount=amount,
        absorbed=absorbed,
        resisted=resisted,
        blocked=blocked,
        stacks=stacks,
        miss=miss,
        critical=critical,
        pet=source_pet,
        target_pet=target_pet,
        flags=tuple(dict.fromkeys(flags)),
        candidates=tuple(candidates),
    )


def _unit(text: str | None, roster: FrozenRoster) -> _Actor:
    raw = _strip(text or "")
    result = resolve_unit_name(raw, roster)
    return _from_resolution(raw, result, spell=None)


def _prefix(
    text: str,
    roster: FrozenRoster,
    known_units: tuple[str, ...],
    *,
    possessive: bool,
) -> _Actor:
    raw = _strip(text)
    result = resolve_source_prefix(raw, roster)
    if result.status in ("resolved", "ambiguous"):
        spell = result.spell or "近战"
        return _from_resolution(raw, result, spell=spell)
    known = _match_known(raw, known_units)
    if known is not None:
        name, spell = known
        return _Actor(name, None, "known_unit", spell or "近战", None, (), (), raw)
    if possessive and "的" in raw:
        left, right = raw.rsplit("的", 1)
        if left and right:
            return _Actor(left, None, "text", right, None, (), (), raw)
    return _Actor(raw, None, "text", "近战" if not possessive else None, None, (), (), raw)


def _from_resolution(raw: str, result: NameResolution, *, spell: str | None) -> _Actor:
    if result.status == "resolved":
        return _Actor(
            result.name,
            result.guid,
            result.method,
            result.spell if result.spell is not None else spell,
            result.pet,
            result.flags,
            (),
            raw,
        )
    if result.status == "ambiguous":
        return _Actor(
            None,
            None,
            "ambiguous_name",
            None,
            None,
            result.flags,
            tuple(item.to_dict() for item in result.candidates),
            raw,
        )
    return _Actor(raw, None, "text", spell, None, (), (), raw)


def _miss_name(text: str) -> str:
    if "招架" in text:
        return "招架"
    if "抵抗" in text:
        return "抵抗"
    if "闪避" in text or "闪躲" in text or "躲闪" in text:
        return "躲闪"
    if "格挡" in text:
        return "格挡"
    return text


def _strip(text: str) -> str:
    return text.strip().rstrip("。.")


def _match_known(text: str, names: tuple[str, ...]) -> tuple[str, str | None] | None:
    for name in sorted(names, key=len, reverse=True):
        if text == name:
            return name, None
        lead = name + "的"
        if text.startswith(lead) and len(text) > len(lead):
            return name, text[len(lead) :]
    return None


def _tail(text: str) -> tuple[int | None, int | None, int | None]:
    absorbed = resisted = blocked = None
    for amount, kind in TAIL_RE.findall(text):
        value = int(amount)
        if kind == "吸收":
            absorbed = value
        elif kind == "抵抗":
            resisted = value
        else:
            blocked = value
    return absorbed, resisted, blocked


def _school(text: str) -> str:
    matched = SCHOOL_RE.search(text)
    if matched:
        return matched.group("school")
    return "物理"


def _template(text: str, roster: FrozenRoster) -> str:
    value = text
    for name in roster.names_by_length:
        value = value.replace(name, "{名}")
    value = re.sub(r"\d+", "#", value)
    return value[:140]
