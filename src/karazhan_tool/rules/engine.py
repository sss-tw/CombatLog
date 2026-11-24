"""规则引擎。由旧版单日分析脚本迁移，日期相关数据全部由 configure() 注入。"""

import json
import re
from collections import Counter, defaultdict
from statistics import median

from karazhan_tool.items import normalize_item_name
from karazhan_tool.parser.names import PRONOUNS


LOG_PATH = None
DATE = None
DATE_PREFIX = None
# 装备快照来源；黄金基准使用的文件不含当日快照，见日期配置说明。
CUSTOM_DATA_PATH = None
# 祝福推断与小怪归属读取的全部 CustomData 文件。
CUSTOM_DATA_FILES = []
CUSTOM_DATA_ANCHOR_MS = None
CUSTOM_DATA_ANCHOR_TS = None
LOGGER_NAME = None
PREP_START = None
ENCOUNTERS = []
EXTRA_BOSS_WINDOWS = []
ATTEMPTS = {}
DEMON_SLAYING_BOSSES = []
WIPE_CAUSES = []
KNOWN_UNITS = ()
RAID_START = None
RAID_END = None
PLAYER_CLASSES = {}
NAME_ISSUES = []
# 玩家在场时段 {玩家: (首条记录秒, 末条记录秒)}；离团后的事不再追责。
PRESENCE = {}
# 装备自带奥抗：手写基础表 + 物品数据库导出表（config/equipment_arcane_resistance.json）。
# 两表都查不到的装备算待补，该玩家奥抗不视为已核验。
ARCANE_RESIST_ITEMS = {}
ARCANE_RESIST_NAMES = {}


def configure(settings):
    """settings 为 karazhan_tool.analyze.build_settings 的结果。"""
    global LOG_PATH, DATE, DATE_PREFIX, CUSTOM_DATA_PATH, CUSTOM_DATA_FILES
    global CUSTOM_DATA_ANCHOR_MS, CUSTOM_DATA_ANCHOR_TS, LOGGER_NAME, PREP_START
    global ENCOUNTERS, EXTRA_BOSS_WINDOWS, ATTEMPTS, DEMON_SLAYING_BOSSES
    global WIPE_CAUSES, KNOWN_UNITS, RAID_START, RAID_END, PLAYER_CLASSES, NAME_ISSUES
    LOG_PATH = settings["combat_log"]
    DATE = settings["date"]
    DATE_PREFIX = settings["date_prefix"]
    CUSTOM_DATA_PATH = settings["gear_snapshot_file"]
    CUSTOM_DATA_FILES = list(settings["custom_data_files"])
    CUSTOM_DATA_ANCHOR_MS = settings["anchor_epoch_ms"]
    CUSTOM_DATA_ANCHOR_TS = settings["anchor_log_time"]
    LOGGER_NAME = settings["logger_name"]
    PREP_START = settings["prep_start"]
    ENCOUNTERS = [tuple(item) for item in settings["encounters"]]
    EXTRA_BOSS_WINDOWS = [tuple(item) for item in settings["extra_boss_windows"]]
    ATTEMPTS = settings["attempts"]
    DEMON_SLAYING_BOSSES = list(settings["demon_slaying_bosses"])
    WIPE_CAUSES = settings["wipe_causes"]
    KNOWN_UNITS = tuple(sorted(settings["known_units"], key=len, reverse=True))
    RAID_START = settings["raid_start"]
    RAID_END = settings["raid_end"]
    PLAYER_CLASSES = dict(settings["player_classes"])
    NAME_ISSUES = []
    ARCANE_RESIST_ITEMS.clear()
    ARCANE_RESIST_ITEMS.update(ARCANE_RESIST_BASE_ITEMS)
    ARCANE_RESIST_ITEMS.update({
        int(item_id): item["arcane"]
        for item_id, item in (settings.get("arcane_resist_items") or {}).items()
    })
    ARCANE_RESIST_NAMES.clear()
    ARCANE_RESIST_NAMES.update(ARCANE_RESIST_BASE_NAMES)
    ARCANE_RESIST_NAMES.update(settings.get("arcane_resist_names") or {})


def encounter_window(boss):
    for name, start, end in ENCOUNTERS:
        if name == boss:
            return start, end
    raise KeyError("日期配置缺少首领区间：%s" % boss)


def compute_presence(rows, roster):
    lo, hi = seconds(RAID_START), seconds(RAID_END)
    spans = {}
    if LOGGER_NAME in roster:
        spans[LOGGER_NAME] = (lo, hi)
    names = sorted((name for name in roster if name != LOGGER_NAME), key=len, reverse=True)
    if not names:
        return spans
    pattern = re.compile("|".join(re.escape(name) for name in names))
    for row in rows:
        if not lo <= row["sec"] <= hi:
            continue
        for match in pattern.finditer(row["body"]):
            name = match.group(0)
            first, last = spans.get(name, (row["sec"], row["sec"]))
            spans[name] = (min(first, row["sec"]), max(last, row["sec"]))
    return spans


def left_at(player):
    """玩家末条记录时间；没有记录时视为全程在场。"""
    span = PRESENCE.get(player)
    return span[1] if span else seconds(RAID_END)


def joined_at(player):
    """玩家首条记录时间；没有记录时视为全程在场。"""
    span = PRESENCE.get(player)
    return span[0] if span else seconds(RAID_START)


def present_in(player, boss):
    attempts = ATTEMPTS.get(boss)
    if not attempts or player not in PRESENCE:
        return True
    first, last = PRESENCE[player]
    return any(
        first <= seconds(item["end"]) and last >= seconds(item["start"])
        for item in attempts
    )


def boss_roster(roster, boss):
    return {player for player in roster if present_in(player, boss)}


def epoch_ms_at(ts):
    return CUSTOM_DATA_ANCHOR_MS + int((seconds(ts) - seconds(CUSTOM_DATA_ANCHOR_TS)) * 1000)


BUFF_GAP_THRESHOLD = 60.0
CONSUMABLE_GAP_THRESHOLD = 60.0
MOON_OUTGOING_ERROR_THRESHOLD = 10000

BUFF_ALIASES = {
    "奥术智慧": "奥术智慧/奥术光辉",
    "奥术光辉": "奥术智慧/奥术光辉",
    "真言术：韧": "耐力（韧/坚韧祷言）",
    "坚韧祷言": "耐力（韧/坚韧祷言）",
    "神圣之灵": "精神（神圣之灵/精神祷言）",
    "精神祷言": "精神（神圣之灵/精神祷言）",
    "野性印记": "野性印记/野性赐福",
    "野性赐福": "野性印记/野性赐福",
    "强效力量祝福": "强效力量祝福",
    "强效智慧祝福": "强效智慧祝福",
    "强效王者祝福": "强效王者祝福",
    "强效拯救祝福": "强效拯救祝福",
    "强效光明祝福": "强效光明祝福",
    "强效庇护祝福": "强效庇护祝福",
    "战斗怒吼": "战斗怒吼",
    "强击光环": "强击光环",
    "枭兽光环": "枭兽光环",
    "生命之树光环": "生命之树光环",
    "虔诚光环": "虔诚光环",
    "专注光环": "专注光环",
}

TRACKED_COVERAGE_BUFFS = {
    "奥术智慧/奥术光辉",
    "耐力（韧/坚韧祷言）",
    "精神（神圣之灵/精神祷言）",
    "野性印记/野性赐福",
    "强效力量祝福",
    "强效智慧祝福",
    "强效王者祝福",
    "强效拯救祝福",
    "强效光明祝福",
    "强效庇护祝福",
}

GREATER_BLESSING_IDS = {
    25782: "强效力量祝福",
    25916: "强效力量祝福",
    25894: "强效智慧祝福",
    25918: "强效智慧祝福",
    25898: "强效王者祝福",
    25895: "强效拯救祝福",
    25890: "强效光明祝福",
    25899: "强效庇护祝福",
}

CLASS_SPELLS = {
    "法师": {"火球术", "炎爆术", "灼烧", "寒冰箭", "奥术飞弹", "奥术冲击", "奥术弹幕", "火焰冲击"},
    "术士": {"暗影箭", "腐蚀术", "痛苦诅咒", "生命虹吸", "暗影灼烧", "灵魂之火", "献祭"},
    "平衡德": {"星火术", "愤怒", "月火术", "虫群", "艾露恩灌注"},
    "野性德": {"切碎", "撕碎", "割伤", "挥击", "野蛮撕咬", "爪击"},
    "猎人": {"自动射击", "稳固射击", "瞄准射击", "多重射击", "奥术射击", "猛禽一击", "穿刺射击"},
    "盗贼": {"背刺", "邪恶攻击", "剔骨", "出血", "速效毒药 VI", "剧毒涌动"},
    "战士": {"英勇打击", "嗜血", "致死打击", "旋风斩", "旋风斩击", "重伤", "压制", "盾牌猛击"},
    "圣骑士": {"神圣打击", "十字军打击", "奉献", "命令圣印", "正义圣印", "智慧圣印"},
    "牧师": {"精神鞭笞", "心灵震爆", "暗言术：痛", "噬灵瘟疫", "神圣之火"},
    "萨满": {"闪电箭", "闪电链", "风暴打击", "火舌攻击", "闪电之盾"},
}

MAGIC_SCHOOLS = ("火焰", "冰霜", "奥术", "暗影", "自然", "神圣")
DISPEL_SPELLS = ("驱散魔法", "解除诅咒", "解除次级诅咒", "净化", "净化术", "清洁术", "消毒术", "驱毒术", "祛病术")
CURSES = ("暗影诅咒", "元素诅咒", "鲁莽诅咒", "语言诅咒", "虚弱诅咒", "痛苦诅咒")
DRUID_HEALING_SPELLS = ("治疗之触", "回春术", "愈合", "迅捷治愈", "宁静", "生命绽放", "生命之花")
HEALING_SPELLS = {
    "治疗之触", "回春术", "愈合", "迅捷治愈", "宁静", "生命绽放", "生命之花",
    "快速治疗", "治疗术", "强效治疗术", "治疗祷言", "恢复", "真言术：盾",
    "治疗链", "治疗波", "次级治疗波",
    "圣光闪现", "圣光术", "神圣震击", "晨辉",
}
PRIMARY_TANK_SPELLS = {"盾牌猛击", "槌击", "神圣之盾"}
SECONDARY_TANK_SPELLS = {"复仇", "盾牌格挡", "破甲攻击", "嘲讽", "低吼", "挑战怒吼"}
HUNTER_RANGED_SPELLS = {
    "自动射击", "稳固射击", "瞄准射击", "多重射击", "奥术射击",
    "乱射", "毒蛇钉刺", "穿刺射击", "额外射击", "爆炸弹药",
    "魔力弹药", "剧毒弹药",
}
HUNTER_MELEE_SPELLS = {
    "近战", "猛禽一击", "猫鼬撕咬", "割伤", "切碎", "摔绊",
}

RAID_GROUPS = {}


def seconds(ts):
    hour, minute, rest = ts.split(":")
    second, millis = rest.split(".")
    return int(hour) * 3600 + int(minute) * 60 + int(second) + int(millis) / 1000


def parse_lines():
    rows = []
    with open(LOG_PATH, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.startswith(DATE_PREFIX):
                continue
            match = re.match(re.escape(DATE_PREFIX) + r"(\d\d:\d\d:\d\d\.\d\d\d)  (.*)", line.rstrip())
            if match:
                rows.append({"line": number, "ts": match.group(1), "sec": seconds(match.group(1)), "body": match.group(2)})
    return rows


def aura_holders_at(rows, roster, aura, cutoff_sec):
    state = {}
    for row in rows:
        if row["sec"] > cutoff_sec:
            break
        gain = re.match(r"(.+?)(?:获得了|受到了)" + re.escape(aura) + r"(?:的效果|效果的影响)", row["body"])
        if gain:
            player = normalize_unit(gain.group(1))
            if player in roster:
                state[player] = True
        loss = re.match(re.escape(aura) + r"效果从(.+?)身上消失", row["body"])
        if loss:
            player = normalize_unit(loss.group(1))
            if player in roster:
                state[player] = False
    return {player for player in roster if state.get(player)}


def _name_issue(raw, chosen, candidates, reason):
    key = (raw, chosen, reason)
    for item in NAME_ISSUES:
        if item["key"] == key:
            item["count"] += 1
            return
    NAME_ISSUES.append({
        "key": key,
        "raw": raw,
        "chosen": chosen,
        "candidates": candidates,
        "reason": reason,
        "count": 1,
    })


def normalize_unit(name):
    name = name.strip()
    if name in PRONOUNS:
        if name in PLAYER_CLASSES:
            _name_issue(name, name, [name, LOGGER_NAME], "ambiguous_name")
            return name
        return LOGGER_NAME
    owner = re.search(r"\(([^()]+)\)$", name)
    if owner:
        owner_name = owner.group(1)
        if owner_name in PRONOUNS and owner_name not in PLAYER_CLASSES:
            return LOGGER_NAME
        return owner_name
    return name


def build_roster(rows):
    # 名单在解析前已由 CustomData 与 RAW 日志冻结。
    return set(PLAYER_CLASSES)


def _roster_source(prefix, candidates):
    for player in candidates:
        if prefix == player:
            return player, "近战"
        if prefix.startswith(player + "的"):
            return player, prefix[len(player) + 1:]
        # Pet/guardian source: "Pet (owner)"
        if prefix.endswith("(" + player + ")"):
            return player, "宠物近战"
        marker = "(" + player + ")的"
        if marker in prefix:
            return player, "宠物：" + prefix.split(marker, 1)[1]
    return None


def split_source(prefix, roster):
    candidates = sorted(roster, key=len, reverse=True)
    pronoun = None
    if prefix.startswith("你的") and len(prefix) > 2:
        pronoun = (LOGGER_NAME, prefix[2:])
    elif prefix == "你":
        pronoun = (LOGGER_NAME, "近战")
    named = _roster_source(prefix, candidates)
    if pronoun is not None:
        if named is not None and named[0] != LOGGER_NAME:
            _name_issue(prefix, named[0], [named[0], LOGGER_NAME], "ambiguous_name")
            return named
        return pronoun
    if prefix in KNOWN_UNITS:
        return prefix, "近战"
    if named is not None:
        return named
    if "的" in prefix:
        source, spell = prefix.rsplit("的", 1)
        return normalize_unit(source), spell
    return normalize_unit(prefix), "近战"


def parse_damage(body, roster):
    damage_match = re.search(r"(?:造成|受到了)(\d+)(?:点|的致命一击)", body)
    if not damage_match:
        return None
    marker = None
    marker_index = None
    for candidate in ("致命一击对", "击中", "使", "对"):
        index = body.find(candidate)
        if index >= 0 and (marker_index is None or index < marker_index):
            marker = candidate
            marker_index = index
    if marker is None:
        return None
    prefix = body[:marker_index]
    remainder = body[marker_index + len(marker):]
    target_end = remainder.find("造成")
    received_end = remainder.find("受到了")
    ends = [value for value in (target_end, received_end) if value >= 0]
    if not ends:
        return None
    target = remainder[:min(ends)]
    source, spell = split_source(prefix, roster)
    school = "物理"
    for candidate in MAGIC_SCHOOLS:
        if candidate + "伤害" in body:
            school = candidate
            break
    return {
        "source": source,
        "spell": spell or "近战",
        "target": normalize_unit(target),
        "damage": int(damage_match.group(1)),
        "school": school,
    }


def infer_class(spells):
    scores = {}
    for class_name, identifying in CLASS_SPELLS.items():
        scores[class_name] = sum(value for spell, value in spells.items() if spell in identifying or any(spell.startswith(x) for x in identifying))
    class_name, score = max(scores.items(), key=lambda item: item[1])
    if score == 0:
        return "未识别"
    return class_name


def role_group(class_name, school_damage):
    if class_name == "猎人":
        return "物理"
    if class_name in ("法师", "术士", "平衡德", "牧师"):
        return "法系"
    if class_name in ("战士", "盗贼", "野性德"):
        return "物理"
    magic = sum(value for school, value in school_damage.items() if school != "物理")
    physical = school_damage.get("物理", 0)
    return "法系" if magic > physical else "物理"


def combat_windows(parsed_damage, roster, start_sec=None, end_sec=None, gap=10.0):
    start_sec = seconds(RAID_START) if start_sec is None else start_sec
    end_sec = seconds(RAID_END) if end_sec is None else end_sec
    moments = sorted(
        event["sec"] for event in parsed_damage
        if event["source"] in roster
        and event["target"] not in roster
        and start_sec <= event["sec"] <= end_sec
    )
    if not moments:
        return []
    windows = []
    left = moments[0]
    previous = moments[0]
    for moment in moments[1:]:
        if moment - previous > gap:
            windows.append((left, max(previous, left + 1.0)))
            left = moment
        previous = moment
    windows.append((left, max(previous, left + 1.0)))
    return windows


def combat_overlap_duration(start_sec, end_sec, windows):
    return sum(
        max(0, min(end_sec, right) - max(start_sec, left))
        for left, right in windows
    )


def clock_label(value):
    hour = int(value // 3600)
    minute = int((value % 3600) // 60)
    second = value % 60
    return "%02d:%02d:%06.3f" % (hour, minute, second)


def analyze_add_first_targets(rows, roster, parsed_damage, roles):
    raid_start_sec, raid_end_sec = seconds(RAID_START), seconds(RAID_END)
    combat_moments = sorted(
        event["sec"] for event in parsed_damage
        if raid_start_sec <= event["sec"] <= raid_end_sec
        and (
            (event["source"] in roster and event["target"] not in roster)
            or (event["target"] in roster and event["source"] not in roster)
        )
    )
    windows = []
    if combat_moments:
        left = combat_moments[0]
        previous = combat_moments[0]
        for moment in combat_moments[1:]:
            if moment - previous > 10.0:
                windows.append((left, max(previous, left + 1.0)))
                left = moment
            previous = moment
        windows.append((left, max(previous, left + 1.0)))

    deaths = []
    for row in rows:
        if not (raid_start_sec <= row["sec"] <= raid_end_sec):
            continue
        death = re.match(r"(.+?)死亡了。", row["body"])
        if death:
            player = normalize_unit(death.group(1))
            if player in roster:
                deaths.append({"player": player, "sec": row["sec"]})

    mass_death_windows = []
    boss_windows = [
        (seconds(start), seconds(end))
        for unused_boss, start, end in ENCOUNTERS
    ] + [
        (seconds(start), seconds(end))
        for start, end in EXTRA_BOSS_WINDOWS
    ]
    for left, right in windows:
        if any(
            min(right, boss_end) >= max(left, boss_start)
            for boss_start, boss_end in boss_windows
        ):
            continue
        window_deaths = sorted({
            item["player"] for item in deaths
            if left - 0.5 <= item["sec"] <= right + 0.5
        })
        if len(window_deaths) >= 4:
            mass_death_windows.append({
                "left": left,
                "right": right,
                "deaths": window_deaths,
            })

    if not mass_death_windows:
        return {
            "method": "按伤害事件间隔10秒切分战斗；排除Boss战，仅保留至少4名不同玩家死亡的小怪战斗段",
            "waves": [],
        }

    anchor_epoch_ms = CUSTOM_DATA_ANCHOR_MS
    anchor_sec = seconds(CUSTOM_DATA_ANCHOR_TS)
    range_start_ms = anchor_epoch_ms + int((raid_start_sec - anchor_sec - 3.0) * 1000)
    range_end_ms = anchor_epoch_ms + int((raid_end_sec - anchor_sec + 3.0) * 1000)
    paths = sorted(set(CUSTOM_DATA_FILES))
    guid_names = {}
    attack_events = []
    seen_events = set()
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                fields = line.rstrip().split("|")
                if len(fields) < 3:
                    continue
                try:
                    timestamp = int(fields[0])
                except ValueError:
                    continue
                if not (range_start_ms <= timestamp <= range_end_ms):
                    continue
                event_type = fields[1]
                if event_type == "UNIT_INFO" and len(fields) > 4:
                    guid_names[fields[2]] = fields[4]
                    continue
                target_guid = None
                source_guid = None
                spell = event_type
                if event_type in ("SWING", "SPELL_DMG", "RANGE_DMG") and len(fields) > 3:
                    target_guid, source_guid = fields[2], fields[3]
                    if event_type != "SWING" and len(fields) > 4:
                        spell = event_type + " #" + fields[4]
                elif event_type == "SPELL_GO" and len(fields) > 5:
                    source_guid, target_guid = fields[4], fields[5]
                    spell = "SPELL_GO #" + fields[3]
                else:
                    continue
                if not source_guid.startswith("0xF13"):
                    continue
                key = (timestamp, event_type, source_guid, target_guid, spell)
                if key in seen_events:
                    continue
                seen_events.add(key)
                attack_events.append({
                    "timestamp": timestamp,
                    "sec": anchor_sec + (timestamp - anchor_epoch_ms) / 1000.0,
                    "source_guid": source_guid,
                    "target_guid": target_guid,
                    "event": spell,
                })

    player_by_guid = {
        guid: name for guid, name in guid_names.items() if name in roster
    }
    role_by_name = {item["name"]: item["role"] for item in roles}
    boss_names = set(item[0].replace("（国际象棋）", "") for item in ENCOUNTERS)
    first_targets = []
    battle_rows = []
    for battle_index, battle in enumerate(mass_death_windows, 1):
        battle_label = "ADD-%d · %s–%s" % (
            battle_index,
            clock_label(battle["left"]),
            clock_label(battle["right"]),
        )
        battle_rows.append({
            "battle": battle_label,
            "death_count": len(battle["deaths"]),
        })
        candidates = [
            item for item in attack_events
            if battle["left"] - 2.0 <= item["sec"] <= battle["right"] + 0.5
            and item["target_guid"] in player_by_guid
            and guid_names.get(item["source_guid"])
            and guid_names.get(item["source_guid"]) not in boss_names
        ]
        first_by_guid = {}
        for item in sorted(candidates, key=lambda value: value["timestamp"]):
            first_by_guid.setdefault(item["source_guid"], item)
        duplicate_counts = Counter(
            guid_names[guid] for guid in first_by_guid
        )
        duplicate_index = Counter()
        for guid, item in sorted(
            first_by_guid.items(), key=lambda pair: pair[1]["timestamp"]
        ):
            monster = guid_names[guid]
            duplicate_index[monster] += 1
            display_monster = (
                "%s #%d" % (monster, duplicate_index[monster])
                if duplicate_counts[monster] > 1 else monster
            )
            target = player_by_guid[item["target_guid"]]
            target_role = role_by_name.get(target, "未识别")
            spell_actions = []
            if target_role == "治疗":
                aliases = (target, "你") if target == LOGGER_NAME and "你" not in PLAYER_CLASSES else (target,)
                for row in rows:
                    if not (item["sec"] - 5.0 <= row["sec"] <= item["sec"] + 0.25):
                        continue
                    body = row["body"]
                    if any(
                        body.startswith(alias + "开始施放")
                        or (body.startswith(alias + "对") and "施放了" in body)
                        or (
                            body.startswith(alias + "的")
                            and ("恢复了" in body or "治疗" in body)
                        )
                        for alias in aliases
                    ):
                        spell_actions.append("%s %s" % (row["ts"], body))
                spell_actions = spell_actions[-3:]
            first_targets.append({
                "battle": battle_label,
                "monster_name": monster,
                "monster": display_monster,
                "_sec": item["sec"],
                "first_attack": clock_label(item["sec"]),
                "target": target,
                "target_role": target_role,
                "event": item["event"],
                "healer_cast_check": (
                    "；".join(spell_actions)
                    if spell_actions
                    else (
                        "治疗；首次攻击前5秒未见明确施法或治疗动作"
                        if target_role == "治疗" else "非治疗，不检查"
                    )
                ),
            })
    wave_groups = []
    for battle in battle_rows:
        battle_targets = [
            item for item in first_targets
            if item["battle"] == battle["battle"]
        ]
        by_monster = defaultdict(list)
        for item in battle_targets:
            by_monster[item["monster_name"]].append(item)
        for monster, items in sorted(
            by_monster.items(),
            key=lambda pair: min(item["_sec"] for item in pair[1]),
        ):
            waves = []
            for item in sorted(items, key=lambda value: value["_sec"]):
                if not waves or item["_sec"] - waves[-1][-1]["_sec"] > 2.0:
                    waves.append([item])
                else:
                    waves[-1].append(item)
            for wave_index, wave in enumerate(waves, 1):
                target_counts = Counter(
                    (item["target"], item["target_role"]) for item in wave
                )
                target_summary = "；".join(
                    "%s（%s）×%d" % (target, role, count)
                    for (target, role), count in target_counts.most_common()
                )
                healer_checks = []
                for item in wave:
                    if item["target_role"] != "治疗":
                        continue
                    check = "%s：%s" % (
                        item["target"], item["healer_cast_check"]
                    )
                    if check not in healer_checks:
                        healer_checks.append(check)
                event_counts = Counter(item["event"] for item in wave)
                wave_groups.append({
                    "battle": battle["battle"],
                    "death_count": battle["death_count"],
                    "wave": "%s 第%d波" % (monster, wave_index),
                    "monster_count": len(wave),
                    "first_attack_span": (
                        wave[0]["first_attack"]
                        if len(wave) == 1 else
                        "%s–%s" % (
                            wave[0]["first_attack"], wave[-1]["first_attack"]
                        )
                    ),
                    "first_targets": target_summary,
                    "events": "；".join(
                        "%s×%d" % (event, count)
                        for event, count in event_counts.most_common()
                    ),
                    "healer_cast_check": (
                        "；".join(healer_checks)
                        if healer_checks else "本波首次目标无治疗"
                    ),
                })
    return {
        "method": (
            "按伤害事件间隔10秒切分战斗；排除Boss战，仅保留至少4名不同玩家死亡的小怪战斗段。"
            "每只非首领NPC按唯一GUID取首次对玩家的SWING、SPELL_DMG、RANGE_DMG或定向SPELL_GO；"
            "这表示首次观察到的攻击目标，不等同于客户端未记录的初始仇恨表。"
        ),
        "waves": wave_groups,
    }


def analyze_dps(rows, roster):
    parsed = []
    for row in rows:
        damage = parse_damage(row["body"], roster)
        if damage:
            damage.update({"ts": row["ts"], "sec": row["sec"], "line": row["line"]})
            parsed.append(damage)

    encounter_rows = []
    total_by_player = defaultdict(int)
    total_spells = defaultdict(Counter)
    total_schools = defaultdict(Counter)
    raid_start_sec, raid_end_sec = seconds(RAID_START), seconds(RAID_END)
    for event in parsed:
        if not (raid_start_sec <= event["sec"] <= raid_end_sec):
            continue
        if event["source"] not in roster or event["target"] in roster:
            continue
        total_by_player[event["source"]] += event["damage"]
        total_spells[event["source"]][event["spell"]] += event["damage"]
        total_schools[event["source"]][event["school"]] += event["damage"]

    for boss, start, end in ENCOUNTERS:
        start_sec, end_sec = seconds(start), seconds(end)
        damage_by_player = defaultdict(int)
        spells = defaultdict(Counter)
        schools = defaultdict(Counter)
        for event in parsed:
            if not (start_sec <= event["sec"] <= end_sec):
                continue
            if event["source"] not in roster or event["target"] in roster:
                continue
            damage_by_player[event["source"]] += event["damage"]
            spells[event["source"]][event["spell"]] += event["damage"]
            schools[event["source"]][event["school"]] += event["damage"]
        duration = end_sec - start_sec
        encounter_rows.append({
            "boss": boss,
            "start": start,
            "end": end,
            "duration": round(duration, 3),
            "raid_damage": sum(damage_by_player.values()),
            "raid_dps": round(sum(damage_by_player.values()) / duration, 1),
            "players": [{
                "name": player,
                "damage": damage,
                "dps": round(damage / duration, 1),
                "top_skills": spells[player].most_common(5),
            } for player, damage in sorted(damage_by_player.items(), key=lambda item: -item[1])],
        })

    windows = combat_windows(parsed, roster)
    total_duration = sum(right - left for left, right in windows)
    players = []
    for player, damage in sorted(total_by_player.items(), key=lambda item: -item[1]):
        class_name = infer_class(total_spells[player])
        players.append({
            "name": player,
            "class": class_name,
            "group": role_group(class_name, total_schools[player]),
            "damage": damage,
            "dps": round(damage / total_duration, 1),
            "top_skills": total_spells[player].most_common(8),
            "schools": dict(total_schools[player]),
        })
    return {
        "scope_start": RAID_START,
        "scope_end": RAID_END,
        "elapsed_time": round(raid_end_sec - raid_start_sec, 3),
        "active_combat_time": round(total_duration, 3),
        "combat_windows": [{"start": left, "end": right, "duration": round(right - left, 3)} for left, right in windows],
        "players": players,
        "encounters": encounter_rows,
    }, parsed


def analyze_roles(rows, roster, parsed_damage, dps_players):
    raid_start_sec, raid_end_sec = seconds(RAID_START), seconds(RAID_END)
    damage_by_player = defaultdict(Counter)
    damage_amount_by_player = defaultdict(Counter)
    damage_actions = Counter()
    for event in parsed_damage:
        if (
            raid_start_sec <= event["sec"] <= raid_end_sec
            and event["source"] in roster
            and event["target"] not in roster
        ):
            damage_by_player[event["source"]][event["spell"]] += 1
            damage_amount_by_player[event["source"]][event["spell"]] += event["damage"]
            damage_actions[event["source"]] += 1

    healing_actions = defaultdict(set)
    healing_amount = Counter()
    healing_spells = defaultdict(Counter)
    tank_spells = defaultdict(Counter)
    for row in rows:
        if not (raid_start_sec <= row["sec"] <= raid_end_sec):
            continue
        direct = re.match(
            r"(.+?)的(.+?)(?:发挥极效，)?为.+?恢复了(\d+)点生命值",
            row["body"],
        )
        periodic = re.match(
            r".+?获得了(\d+)点生命值（(.+?)的(.+?)）。",
            row["body"],
        )
        if direct:
            source = normalize_unit(direct.group(1))
            spell = direct.group(2)
            amount = int(direct.group(3))
        elif periodic:
            source = normalize_unit(periodic.group(2))
            spell = periodic.group(3)
            amount = int(periodic.group(1))
        else:
            source, spell, amount = None, None, 0
        if source in roster and spell in HEALING_SPELLS:
            healing_actions[source].add((spell, round(row["sec"], 1)))
            healing_amount[source] += amount
            healing_spells[source][spell] += 1

        tank_cast = re.match(
            r"(.+?)(?:对.+?)?(?:施放了|使用)(盾牌格挡|嘲讽|低吼|挑战怒吼)",
            row["body"],
        )
        if tank_cast:
            source = normalize_unit(tank_cast.group(1))
            if source in roster:
                tank_spells[source][tank_cast.group(2)] += 1

    for player, spells in damage_by_player.items():
        for spell, count in spells.items():
            if spell in PRIMARY_TANK_SPELLS or spell in SECONDARY_TANK_SPELLS:
                tank_spells[player][spell] += count

    inferred_class = {item["name"]: item["class"] for item in dps_players}
    roles = []
    for player in sorted(roster):
        primary_tank = sum(tank_spells[player][spell] for spell in PRIMARY_TANK_SPELLS)
        secondary_tank = sum(tank_spells[player][spell] for spell in SECONDARY_TANK_SPELLS)
        heal_count = len(healing_actions[player])
        is_tank = primary_tank >= 10 or (primary_tank >= 5 and secondary_tank >= 2)
        # Off-healing alone does not make a damage dealer a healer.  Require
        # healing activity to be substantial relative to offensive actions.
        is_healer = heal_count >= 20 and damage_actions[player] <= heal_count * 2
        base_class = PLAYER_CLASSES.get(player, "未知")
        combat_class = inferred_class.get(player, base_class)
        hunter_melee_damage = sum(
            damage_amount_by_player[player][spell]
            for spell in HUNTER_MELEE_SPELLS
        )
        hunter_ranged_damage = sum(
            damage_amount_by_player[player][spell]
            for spell in HUNTER_RANGED_SPELLS
        )
        hunter_is_melee = (
            base_class == "猎人"
            and hunter_melee_damage > hunter_ranged_damage
        )
        shaman_is_melee = (
            base_class == "萨满"
            and damage_by_player[player]["近战"] > 0
        )
        if is_tank:
            role = "坦克"
        elif is_healer:
            role = "治疗"
        elif base_class == "猎人":
            role = "物理近战" if hunter_is_melee else "物理远程"
        elif base_class == "圣骑士" or shaman_is_melee:
            role = "物理近战"
        elif base_class in ("战士", "盗贼") or combat_class == "野性德":
            role = "物理近战"
        else:
            role = "法术远程"

        evidence = Counter()
        if role == "坦克":
            evidence.update(tank_spells[player])
        elif role == "治疗":
            evidence.update(healing_spells[player])
        else:
            evidence.update(damage_by_player[player])
        roles.append({
            "name": player,
            "class": base_class,
            "role": role,
            "healing_actions": heal_count,
            "healing": healing_amount[player],
            "damage_actions": damage_actions[player],
            "tank_actions": primary_tank + secondary_tank,
            "hunter_melee_damage": hunter_melee_damage if base_class == "猎人" else None,
            "hunter_ranged_damage": hunter_ranged_damage if base_class == "猎人" else None,
            "evidence": evidence.most_common(5),
        })
    return roles


def aura_name(raw):
    for name, canonical in BUFF_ALIASES.items():
        if raw == name:
            return canonical
    return None


def infer_paladin_blessing_assignments(roster):
    raid_start_ms = epoch_ms_at(RAID_START)
    raid_end_ms = epoch_ms_at(RAID_END)
    paths = sorted(set(CUSTOM_DATA_FILES))
    guid_names = {}
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if "|UNIT_INFO|" not in line:
                    continue
                fields = line.rstrip().split("|")
                if len(fields) >= 5 and fields[4] in roster:
                    guid_names[fields[2]] = fields[4]

    casts = defaultdict(Counter)
    seen = set()
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if "|SPELL_GO|" not in line:
                    continue
                fields = line.rstrip().split("|")
                if len(fields) < 6:
                    continue
                timestamp = int(fields[0])
                spell_id = int(fields[3])
                if not (raid_start_ms <= timestamp <= raid_end_ms):
                    continue
                if spell_id not in GREATER_BLESSING_IDS:
                    continue
                source = guid_names.get(fields[4])
                if not source or PLAYER_CLASSES.get(source) != "圣骑士":
                    continue
                event_key = (timestamp, spell_id, fields[4], fields[5])
                if event_key in seen:
                    continue
                seen.add(event_key)
                casts[source][GREATER_BLESSING_IDS[spell_id]] += 1

    assignments = {}
    for player, counts in casts.items():
        if not counts:
            continue
        highest = max(counts.values())
        dominant = sorted(name for name, count in counts.items() if count == highest)
        assignments[player] = {
            "blessing": dominant[0] if len(dominant) == 1 else None,
            "dominant_candidates": dominant,
            "counts": dict(sorted(counts.items())),
            "ambiguous": len(dominant) != 1,
        }
    return assignments


def analyze_buffs(rows, roster, roles):
    events = defaultdict(lambda: defaultdict(list))
    source_evidence = defaultdict(Counter)
    for row in rows:
        body = row["body"]
        gain = re.match(r"(.+?)获得了(.+?)的效果", body)
        if gain:
            player = normalize_unit(gain.group(1))
            canonical = aura_name(gain.group(2))
            if player in roster and canonical:
                events[canonical][player].append(("gain", row["sec"], row["ts"], row["line"]))
        loss = re.match(r"(.+?)效果从(.+?)身上消失", body)
        if loss:
            player = normalize_unit(loss.group(2))
            canonical = aura_name(loss.group(1))
            if player in roster and canonical:
                events[canonical][player].append(("loss", row["sec"], row["ts"], row["line"]))
        evidence = re.match(r".+?从(.+?)的(.+?)获得了\d+点(?:法力值|生命值)", body)
        if evidence:
            canonical = aura_name(evidence.group(2))
            source = normalize_unit(evidence.group(1))
            if canonical and source in roster:
                source_evidence[canonical][source] += 1

    class_members = defaultdict(list)
    for name in sorted(roster):
        class_members[PLAYER_CLASSES.get(name, "未知")].append(name)
    resto_druids = [
        item["name"] for item in roles
        if item["class"] == "德鲁伊" and item["role"] == "治疗"
    ]
    role_by_name = {item["name"]: item for item in roles}
    provider_candidates = {
        "奥术智慧/奥术光辉": class_members["法师"],
        "野性印记/野性赐福": resto_druids,
        "耐力（韧/坚韧祷言）": class_members["牧师"],
        "精神（神圣之灵/精神祷言）": class_members["牧师"],
        "强击光环": class_members["猎人"],
        "枭兽光环": class_members["平衡德"],
        "生命之树光环": class_members["野性德"],
        "强效力量祝福": class_members["圣骑士"],
        "强效智慧祝福": class_members["圣骑士"],
        "强效王者祝福": class_members["圣骑士"],
        "强效拯救祝福": class_members["圣骑士"],
        "强效光明祝福": class_members["圣骑士"],
        "强效庇护祝福": class_members["圣骑士"],
    }

    blessing_assignments = infer_paladin_blessing_assignments(roster)
    assigned_by_blessing = defaultdict(list)
    for player, assignment in blessing_assignments.items():
        if assignment["blessing"]:
            assigned_by_blessing[assignment["blessing"]].append(player)

    summaries = []
    raid_start_sec, raid_end_sec = seconds(RAID_START), seconds(RAID_END)
    for buff, by_player in sorted(events.items()):
        delays = []
        missing = []
        losses = 0
        for player, player_events in by_player.items():
            player_events.sort(key=lambda item: item[1])
            for index, item in enumerate(player_events):
                if item[0] != "loss" or not (raid_start_sec <= item[1] <= raid_end_sec):
                    continue
                losses += 1
                next_gain = next((candidate for candidate in player_events[index + 1:] if candidate[0] == "gain" and candidate[1] <= raid_end_sec), None)
                if next_gain:
                    delay = next_gain[1] - item[1]
                    delays.append({"player": player, "loss": item[2], "gain": next_gain[2], "delay": round(delay, 3), "line": item[3]})
                else:
                    missing.append({"player": player, "loss": item[2], "line": item[3]})
        explicit = [name for name, unused in source_evidence[buff].most_common()]
        summaries.append({
            "buff": buff,
            "explicit_sources": explicit,
            "provider_candidates": provider_candidates.get(buff, []),
            "assigned_providers": sorted(assigned_by_blessing.get(buff, [])),
            "paladin_blessing_assignments": blessing_assignments if buff.startswith("强效") else {},
            "provider_skill_counts": {
                name: role_by_name[name]["healing_actions"] for name in resto_druids
            } if buff == "野性印记/野性赐福" else {},
            "losses": losses,
            "rebuffed": len(delays),
            "median_delay": round(median([item["delay"] for item in delays]), 2) if delays else None,
            "max_delay": round(max([item["delay"] for item in delays]), 2) if delays else None,
            "slow_rebuffs": sorted([
                item for item in delays
                if item["delay"] > BUFF_GAP_THRESHOLD
            ], key=lambda item: item["loss"]),
            "boss_slow_rebuffs": sorted([
                item for item in delays
                if item["delay"] > BUFF_GAP_THRESHOLD
                and any(seconds(start) <= seconds(item["loss"]) <= seconds(end) for unused_boss, start, end in ENCOUNTERS)
            ], key=lambda item: item["loss"]),
            "not_rebuffed": missing[:30],
        })
    return summaries


def point_stage(ts):
    value = seconds(ts)
    short_names = [item[0].replace("守护者", "").replace("魔网观察者", "").replace("（国际象棋）", "") for item in ENCOUNTERS]
    for index, (boss, start, end) in enumerate(ENCOUNTERS):
        if seconds(start) <= value <= seconds(end):
            return short_names[index] + "战内"
        if index < len(ENCOUNTERS) - 1 and seconds(end) < value < seconds(ENCOUNTERS[index + 1][1]):
            return short_names[index] + "→" + short_names[index + 1] + "之间"
    if value < seconds(ENCOUNTERS[0][1]):
        return "开场→" + short_names[0] + "之间"
    return short_names[-1] + "之后"


def analyze_buff_coverage(buff_summaries, parsed_damage, roster, roles):
    incoming = Counter()
    for event in parsed_damage:
        if event["target"] in roster and event["source"] not in roster and seconds(RAID_START) <= event["sec"] <= seconds(RAID_END):
            incoming[event["target"]] += event["damage"]
    tanks = [
        item["name"] for item in roles if item["role"] == "坦克"
    ]
    group_by_player = {}
    for group, members in RAID_GROUPS.items():
        for member in members:
            group_by_player[member] = group
    combat_group_by_player = {
        item["name"]: item["role"] for item in roles
    }
    windows = combat_windows(parsed_damage, roster)
    raw_rows = []
    for summary in buff_summaries:
        if summary["buff"] not in TRACKED_COVERAGE_BUFFS:
            continue
        issues = list(summary["slow_rebuffs"])
        issues.extend({
            "player": item["player"],
            "loss": item["loss"],
            "gain": RAID_END,
            "delay": round(seconds(RAID_END) - seconds(item["loss"]), 2),
            "until_end": True,
        } for item in summary["not_rebuffed"]
          if seconds(item["loss"]) < seconds(RAID_END) - BUFF_GAP_THRESHOLD)
        for issue in issues:
            player = issue["player"]
            providers = list(summary.get("assigned_providers", []))
            gap_start = seconds(issue["loss"])
            gap_end = min(seconds(issue["gain"]), left_at(player))
            if providers:
                gap_start = max(gap_start, min(joined_at(p) for p in providers))
                gap_end = min(gap_end, max(left_at(p) for p in providers))
            if gap_end <= gap_start:
                continue
            combat_duration = combat_overlap_duration(gap_start, gap_end, windows)
            if combat_duration <= BUFF_GAP_THRESHOLD:
                continue
            player_class = PLAYER_CLASSES.get(player, "未识别职业")
            if player_class in ("战士", "盗贼") and summary["buff"] in (
                "奥术智慧/奥术光辉", "强效智慧祝福", "精神（神圣之灵/精神祷言）",
            ):
                continue
            if summary["buff"] == "强效力量祝福" and combat_group_by_player.get(player) in ("治疗", "法术远程"):
                continue
            if summary["buff"].startswith("强效"):
                if summary["buff"] == "强效拯救祝福" and player in tanks:
                    continue
                unit = PLAYER_CLASSES.get(player, "未识别职业")
                mode = "按职业"
            else:
                if RAID_GROUPS:
                    unit = "%d队" % group_by_player.get(player, 0)
                    mode = "按队"
                else:
                    unit = player
                    mode = "按玩家实际记录"
            raw_rows.append({
                "buff": summary["buff"],
                "mode": mode,
                "unit": unit,
                "responsible": providers,
                "start": gap_start,
                "end": gap_end,
                "combat_duration": combat_duration,
                "affected": {player},
                "until_end": issue.get("until_end", False) and gap_end >= seconds(RAID_END),
            })
    rows = []
    for key in sorted(set((item["buff"], item["mode"], item["unit"]) for item in raw_rows)):
        items = sorted([item for item in raw_rows if (item["buff"], item["mode"], item["unit"]) == key], key=lambda item: item["start"])
        merged = []
        for item in items:
            if merged and item["start"] <= merged[-1]["end"] + 5:
                merged[-1]["end"] = max(merged[-1]["end"], item["end"])
                merged[-1]["combat_duration"] = max(
                    merged[-1]["combat_duration"], item["combat_duration"]
                )
                merged[-1]["affected"].update(item["affected"])
                merged[-1]["until_end"] = merged[-1]["until_end"] or item["until_end"]
            else:
                merged.append(item)
        for item in merged:
            loss_ts = next(row["ts"] for row in parsed_damage if row["sec"] >= item["start"])
            gain_ts = next((row["ts"] for row in parsed_damage if row["sec"] >= item["end"]), RAID_END)
            left = point_stage(loss_ts)
            right = point_stage(gain_ts)
            rows.append({
                "buff": item["buff"],
                "mode": item["mode"],
                "unit": item["unit"],
                "responsible": item["responsible"],
                "affected": sorted(item["affected"]),
                "interval": left if left == right else left + " 至 " + right,
                "duration": round(item["combat_duration"], 1),
                "until_end": item["until_end"],
            })
    return {
        "available": True,
        "grouping_available": bool(RAID_GROUPS),
        "reason": (
            None if RAID_GROUPS
            else "未提供本周八队分组；补Buff及时性按每名玩家的实际失效与重新获得记录判断，不合并为队伍"
        ),
        "groups": [{"group": group, "members": list(members)} for group, members in RAID_GROUPS.items()],
        "tanks_by_incoming": [{"name": name, "damage": incoming[name]} for name in tanks],
        "issues": rows,
    }


def analyze_windfury_coverage(rows, parsed_damage, roster, roles):
    if not RAID_GROUPS:
        return {
            "available": False,
            "reason": "未提供本周八队分组，无法可靠判定",
            "method": "需要八队分组后才能按队判断风怒图腾覆盖。",
            "totem_duration": 120.0,
            "combat_duration": None,
            "groups": [],
        }
    air_totems = {
        "风怒图腾", "根基图腾", "风之优雅图腾", "宁静之风图腾",
        "自然抗性图腾", "风墙图腾", "岗哨图腾",
    }
    role_by_name = {item["name"]: item for item in roles}
    raid_start_sec, raid_end_sec = seconds(RAID_START), seconds(RAID_END)
    windows = combat_windows(parsed_damage, roster)
    total_combat = sum(right - left for left, right in windows)
    casts_by_shaman = defaultdict(list)
    for row in rows:
        if not (raid_start_sec - 120.0 <= row["sec"] <= raid_end_sec):
            continue
        cast = re.match(r"(.+?)施放了(.+?图腾)。", row["body"])
        if not cast:
            continue
        player = normalize_unit(cast.group(1))
        spell = cast.group(2)
        if (
            player in roster
            and PLAYER_CLASSES.get(player) == "萨满"
            and spell in air_totems
        ):
            casts_by_shaman[player].append({
                "sec": row["sec"],
                "spell": spell,
            })

    coverage_rows = []
    for group, members in sorted(RAID_GROUPS.items()):
        shamans = [
            player for player in members
            if PLAYER_CLASSES.get(player) == "萨满" and player in roster
        ]
        melee = [
            player for player in members
            if player in role_by_name
            and role_by_name[player]["role"] in ("坦克", "物理近战")
        ]
        if not shamans or not melee:
            continue
        for shaman in shamans:
            casts = sorted(casts_by_shaman[shaman], key=lambda item: item["sec"])
            active = []
            for index, cast in enumerate(casts):
                if cast["spell"] != "风怒图腾":
                    continue
                next_air_sec = (
                    casts[index + 1]["sec"]
                    if index + 1 < len(casts) else raid_end_sec
                )
                end_sec = min(cast["sec"] + 120.0, next_air_sec, raid_end_sec)
                left = max(cast["sec"], raid_start_sec)
                if end_sec <= left:
                    continue
                if active and left <= active[-1][1]:
                    active[-1][1] = max(active[-1][1], end_sec)
                else:
                    active.append([left, end_sec])

            covered_segments = []
            for combat_left, combat_right in windows:
                for active_left, active_right in active:
                    left = max(combat_left, active_left)
                    right = min(combat_right, active_right)
                    if right <= left:
                        continue
                    if covered_segments and left <= covered_segments[-1][1]:
                        covered_segments[-1][1] = max(
                            covered_segments[-1][1], right
                        )
                    else:
                        covered_segments.append([left, right])
            covered = sum(right - left for left, right in covered_segments)

            gaps = []
            for combat_left, combat_right in windows:
                cursor = combat_left
                for active_left, active_right in active:
                    if active_right <= cursor or active_left >= combat_right:
                        continue
                    if active_left > cursor:
                        gaps.append([cursor, min(active_left, combat_right)])
                    cursor = max(cursor, min(active_right, combat_right))
                    if cursor >= combat_right:
                        break
                if cursor < combat_right:
                    gaps.append([cursor, combat_right])
            gaps = [
                {
                    "start_offset": round(left - raid_start_sec, 3),
                    "end_offset": round(right - raid_start_sec, 3),
                    "duration": round(right - left, 3),
                }
                for left, right in gaps if right > left
            ]
            coverage_rows.append({
                "group": group,
                "shaman": shaman,
                "melee_members": melee,
                "error_threshold_pct": 80,
                "is_error": (
                    total_combat > 0
                    and covered / total_combat * 100 < 80
                ),
                "error_weight": len(melee),
                "windfury_casts": sum(
                    1 for item in casts if item["spell"] == "风怒图腾"
                ),
                "combat_duration": round(total_combat, 3),
                "covered_duration": round(covered, 3),
                "uncovered_duration": round(max(0, total_combat - covered), 3),
                "coverage_pct": (
                    round(covered / total_combat * 100, 1)
                    if total_combat else None
                ),
                "gaps": gaps,
                "longest_gap": round(
                    max([item["duration"] for item in gaps] or [0]), 3
                ),
            })
    return {
        "method": "按萨满每次风怒图腾施放起算120秒；施放其他空气图腾时提前终止，并仅与团队实际战斗窗口取交集。",
        "totem_duration": 120.0,
        "combat_duration": round(total_combat, 3),
        "groups": coverage_rows,
    }


def analyze_curses(rows, parsed_damage, roster):
    results = []
    for boss, start, end in ENCOUNTERS:
        start_sec, end_sec = seconds(start), seconds(end)
        if boss == "国王（国际象棋）":
            target_specs = [("主教", 1), ("战车", 1), ("骑士", 1)]
            target_scope = "主教 → 战车 → 骑士"
            phase_bounds = {
                "主教": (start_sec, end_sec),
                "战车": (start_sec, end_sec),
                "骑士": (start_sec, end_sec),
            }
        elif boss == "破碎者鲁普图兰":
            target_specs = [("破碎者鲁普图兰", 1), ("鲁普图兰的碎块", 3)]
            target_scope = "破碎者鲁普图兰 → 3个鲁普图兰的碎块"
            first_fragment_hit = min(
                event["sec"] for event in parsed_damage
                if event["source"] in roster and event["target"] == "鲁普图兰的碎块"
                and start_sec <= event["sec"] <= end_sec
            ) if any(
                event["source"] in roster and event["target"] == "鲁普图兰的碎块"
                and start_sec <= event["sec"] <= end_sec
                for event in parsed_damage
            ) else end_sec
            phase_bounds = {
                "破碎者鲁普图兰": (start_sec, first_fragment_hit),
                "鲁普图兰的碎块": (first_fragment_hit, end_sec),
            }
        else:
            target_specs = [(boss.replace("（国际象棋）", ""), 1)]
            target_scope = target_specs[0][0]
            phase_bounds = {target_scope: (start_sec, end_sec)}
        casts = []
        aura_events = defaultdict(lambda: defaultdict(list))
        indexed_rows = [row for row in rows if start_sec <= row["sec"] <= end_sec]
        for row_index, row in enumerate(indexed_rows):
            for target_name, unused_required in target_specs:
                match = re.match(r"(.+?)对" + re.escape(target_name) + r"施放了(.+?诅咒)", row["body"])
                if match and match.group(2) in CURSES:
                    casts.append({
                        "caster": normalize_unit(match.group(1)),
                        "curse": match.group(2),
                        "target": target_name,
                        "ts": row["ts"],
                        "line": row["line"],
                    })
                applied = re.match(re.escape(target_name) + r"(?:受到了|获得了)(.+?诅咒)(?:效果|的效果)", row["body"])
                if applied and applied.group(1) in CURSES:
                    aura_events[applied.group(1)][target_name].append(("gain", row["sec"], row["ts"]))
                gone = re.match(r"(.+?诅咒)效果从" + re.escape(target_name) + r"身上消失", row["body"])
                if gone and gone.group(1) in CURSES:
                    aura_events[gone.group(1)][target_name].append(("loss", row["sec"], row["ts"]))

        curse_rows = []
        targetable = []
        for target_name, required_count in target_specs:
            phase_left, phase_right = phase_bounds[target_name]
            target_hits = sorted(
                event["sec"] for event in parsed_damage
                if event["source"] in roster and event["target"] == target_name
                and phase_left <= event["sec"] <= phase_right
            )
            if not target_hits:
                continue
            left = target_hits[0]
            previous = target_hits[0]
            for hit in target_hits[1:]:
                if hit - previous > 8:
                    targetable.append((left, max(previous, left + 0.25), target_name, required_count))
                    left = hit
                previous = hit
            targetable.append((left, max(previous, left + 0.25), target_name, required_count))
        targetable.sort()
        coverage_start_sec = start_sec + 2.0
        targetable = [
            (max(left, coverage_start_sec), right, target_name, required_count)
            for left, right, target_name, required_count in targetable
            if right > max(left, coverage_start_sec)
        ]
        targetable_duration = sum(right - left for left, right, unused_target, unused_count in targetable)
        actual_curses = sorted(set(
            [item["curse"] for item in casts]
            + list(aura_events.keys())
        ))
        inferred_assignments = {}
        for curse in actual_curses:
            caster_counts = Counter(
                item["caster"] for item in casts
                if item["curse"] == curse
                and item["caster"] in roster
                and PLAYER_CLASSES.get(item["caster"]) == "术士"
            )
            inferred_assignments[curse] = (
                caster_counts.most_common(1)[0][0] if caster_counts else None
            )
        for curse in actual_curses:
            relevant_casts = [item for item in casts if item["curse"] == curse]
            intervals_by_target = defaultdict(list)
            for target_name, required_count in target_specs:
                timeline = sorted(aura_events[curse][target_name], key=lambda item: item[1])
                active_count = 0
                active_start = None
                for kind, event_sec, unused_ts in timeline:
                    previous_count = active_count
                    if kind == "gain":
                        active_count = min(required_count, active_count + 1)
                    else:
                        active_count = max(0, active_count - 1)
                    if previous_count < required_count and active_count >= required_count:
                        active_start = event_sec
                    elif previous_count >= required_count and active_count < required_count and active_start is not None:
                        intervals_by_target[target_name].append((active_start, min(event_sec, end_sec)))
                        active_start = None
                if active_start is not None:
                    intervals_by_target[target_name].append((active_start, end_sec))
            uptime = union_length(
                interval
                for intervals in intervals_by_target.values()
                for interval in intervals
            )
            targetable_uptime = 0
            for phase_left, phase_right, target_name, unused_count in targetable:
                for active_left, active_right in intervals_by_target[target_name]:
                    targetable_uptime += max(0, min(active_right, phase_right) - max(active_left, phase_left))
            gap_intervals = []
            for phase_left, phase_right, target_name, unused_count in targetable:
                cursor = phase_left
                for active_left, active_right in intervals_by_target[target_name]:
                    if active_right <= cursor or active_left >= phase_right:
                        continue
                    if active_left > cursor:
                        gap_intervals.append((cursor, min(active_left, phase_right), target_name))
                    cursor = max(cursor, min(active_right, phase_right))
                if cursor < phase_right:
                    gap_intervals.append((cursor, phase_right, target_name))
            gap_rows = [{
                "start_offset": round(left - start_sec, 2),
                "end_offset": round(right - start_sec, 2),
                "duration": round(right - left, 2),
                "target": target,
            } for left, right, target in gap_intervals if right - left >= 0.5]
            targetable_uptime_pct = (
                round(targetable_uptime / targetable_duration * 100, 1)
                if targetable_duration else None
            )
            total_gap = round(sum(item["duration"] for item in gap_rows), 2)
            strict_language = boss == "麦迪文的回响" and curse == "语言诅咒"
            ignored_for_error = (
                curse == "暗影诅咒"
                or (curse == "语言诅咒" and boss != "麦迪文的回响")
            )
            coverage_threshold = 80 if boss == "国王（国际象棋）" else 90
            is_error = (
                False
                if ignored_for_error
                else (
                    total_gap >= 0.5
                    if strict_language
                    else (
                        targetable_uptime_pct is not None
                        and targetable_uptime_pct < coverage_threshold
                    )
                )
            )
            curse_rows.append({
                "curse": curse,
                "responsible": inferred_assignments[curse],
                "casters": sorted(set(item["caster"] for item in relevant_casts)),
                "casts": len(relevant_casts),
                "first_cast": relevant_casts[0]["ts"] if relevant_casts else None,
                "first_delay": round(seconds(relevant_casts[0]["ts"]) - start_sec, 2) if relevant_casts else None,
                "uptime_pct": round(uptime / (end_sec - start_sec) * 100, 1),
                "targetable_uptime_pct": targetable_uptime_pct,
                "gap_intervals": gap_rows,
                "total_gap": total_gap,
                "error_rule": (
                    "只展示覆盖率，不计入错误"
                    if ignored_for_error
                    else (
                        "语言诅咒有0.5秒以上实际断档即计错"
                        if strict_language
                        else "覆盖率低于%d%%才计错" % coverage_threshold
                    )
                ),
                "is_error": is_error,
            })
        results.append({
            "boss": boss,
            "start": start,
            "end": end,
            "duration": round(end_sec - start_sec, 2),
            "targetable_duration": round(targetable_duration, 2),
            "coverage_start_offset": 2.0,
            "target_scope": target_scope,
            "assignment_method": "按本场实际施法次数识别每种诅咒的主要施法者；未出现的诅咒不虚构责任。",
            "curses": curse_rows,
        })
    return results


def analyze_dispels(rows, roster, parsed_damage):
    candidates = []
    raid_start_sec, raid_end_sec = seconds(RAID_START), seconds(RAID_END)
    focused_effects = {"奥术压力", "大领主印记"}
    casts = []
    for row in rows:
        if not (raid_start_sec <= row["sec"] <= raid_end_sec):
            continue
        cast = re.match(r"(.+?)对(.+?)施放了(" + "|".join(DISPEL_SPELLS) + r")", row["body"])
        if cast:
            casts.append({
                "sec": row["sec"],
                "ts": row["ts"],
                "caster": normalize_unit(cast.group(1)),
                "target": normalize_unit(cast.group(2)),
                "spell": cast.group(3),
                "line": row["line"],
            })
            continue
        self_cast = re.match(r"(.+?)施放了(" + "|".join(DISPEL_SPELLS) + r")", row["body"])
        if self_cast:
            caster = normalize_unit(self_cast.group(1))
            casts.append({
                "sec": row["sec"],
                "ts": row["ts"],
                "caster": caster,
                "target": caster,
                "spell": self_cast.group(2),
                "line": row["line"],
            })
    focused_removals = []
    for row in rows:
        if not (raid_start_sec <= row["sec"] <= raid_end_sec):
            continue
        remove = re.match(r"(.+?)的(.+?)被移除了", row["body"])
        if not remove or remove.group(2) not in focused_effects:
            continue
        target = normalize_unit(remove.group(1))
        focused_removals.append({
            "row": row,
            "target": target,
            "effect": remove.group(2),
        })

    for removal in focused_removals:
        row = removal["row"]
        target = removal["target"]
        effect = removal["effect"]
        dispel = next((
            item for item in casts
            if abs(item["sec"] - row["sec"]) <= 0.15 and item["target"] == target
        ), None)
        if not dispel:
            continue
        damage_by_target = defaultdict(int)
        damage_details = defaultdict(Counter)
        for event in parsed_damage:
            if effect == "奥术压力":
                correct_damage = (
                    event["source"] == "异常的法力的溢出"
                    and event["spell"] == "奥术能量"
                    and row["sec"] <= event["sec"] <= row["sec"] + 0.75
                )
            else:
                nearby_mark_removals = [
                    item for item in focused_removals
                    if item["effect"] == "大领主印记"
                    and abs(item["row"]["sec"] - event["sec"]) <= 0.1
                ]
                nearest_removal = min(
                    nearby_mark_removals,
                    key=lambda item: abs(item["row"]["sec"] - event["sec"]),
                ) if nearby_mark_removals else None
                correct_damage = (
                    event["source"] == "库鲁尔"
                    and event["spell"] == "暗影新星"
                    and event["damage"] >= 5000
                    and nearest_removal is removal
                )
            if correct_damage and event["target"] in roster:
                damage_by_target[event["target"]] += event["damage"]
                damage_details[event["target"]][event["source"] + "·" + event["spell"]] += event["damage"]
        minimum_damage = 800 if effect == "奥术压力" else 5000
        minimum_players = 3 if effect == "奥术压力" else 1
        significant = {
            player: value for player, value in damage_by_target.items()
            if value >= minimum_damage
        }
        if len(significant) >= minimum_players:
            candidates.append({
                "ts": row["ts"],
                "line": row["line"],
                "encounter": (
                    "阿诺玛鲁斯前小怪（溢出的法力）"
                    if effect == "奥术压力" else "库鲁尔"
                ),
                "caster": dispel["caster"],
                "target": target,
                "dispel": dispel["spell"],
                "removed": effect,
                "hit_players": len(significant),
                "raid_damage_075s": sum(significant.values()),
                "players": [{
                    "name": player,
                    "damage": value,
                    "sources": damage_details[player].most_common(),
                } for player, value in sorted(significant.items(), key=lambda item: -item[1])],
            })
    return candidates


def analyze_sanf(rows, roster, parsed_damage, roles):
    attempts = [dict(item) for item in ATTEMPTS["桑夫·塔斯达尔"]]
    kill = [item for item in attempts if item["result"] == "击杀"][-1]
    start = kill["start"]
    end = kill["end"]
    start_sec, end_sec = seconds(start), seconds(end)
    wipe_rows = []
    for attempt in attempts:
        if attempt is kill:
            attempt["deaths"] = []
            attempt["key_mechanic_timeline"] = []
            continue
        first_start_sec = seconds(attempt["start"])
        first_rows = [
            row for row in rows
            if first_start_sec <= row["sec"] <= seconds(attempt["end"])
        ]
        wipe_rows.append((attempt, first_start_sec, first_rows))
        attempt["deaths"], attempt["key_mechanic_timeline"] = _sanf_wipe_timeline(
            first_rows, first_start_sec, roster
        )
        attempt["review_note"] = "仅列日志可确认的死亡与机制时间线，不强行唯一归因个人责任。"
    sanf_rows = [
        row for row in rows
        if start_sec - 2.0 <= row["sec"] <= end_sec
    ]
    return _analyze_sanf_kill(
        rows, roster, parsed_damage, roles, attempts, wipe_rows,
        start, end, start_sec, end_sec, sanf_rows,
    )


def _sanf_wipe_timeline(first_rows, first_start_sec, roster):
    first_deaths = []
    first_timeline = []
    first_wave_moments = {}
    for row in first_rows:
        death = re.match(r"(.+?)死亡了。", row["body"])
        if death and normalize_unit(death.group(1)) in roster:
            first_deaths.append({
                "offset": round(row["sec"] - first_start_sec, 3),
                "player": normalize_unit(death.group(1)),
            })
        boss_cast = re.match(
            r"桑夫·塔斯达尔开始施放(裂隙回馈|仇恨溢出|裂隙诅咒)",
            row["body"],
        )
        if boss_cast:
            first_timeline.append({
                "offset": round(row["sec"] - first_start_sec, 3),
                "event": row["body"],
            })
        mechanic_gain = re.match(
            r".+?受到了(裂隙诅咒|裂隙纠缠)效果的影响",
            row["body"],
        )
        if mechanic_gain:
            mechanic = mechanic_gain.group(1)
            previous = first_wave_moments.get(mechanic)
            if previous is None or row["sec"] - previous > 0.5:
                first_timeline.append({
                    "offset": round(row["sec"] - first_start_sec, 3),
                    "event": mechanic + "一轮开始",
                })
                first_wave_moments[mechanic] = row["sec"]
    first_timeline.sort(key=lambda item: item["offset"])
    return first_deaths, first_timeline


def _analyze_sanf_kill(
    rows, roster, parsed_damage, roles, attempts, wipe_rows,
    start, end, start_sec, end_sec, sanf_rows,
):
    row_bodies = {row["line"]: row["body"] for row in sanf_rows}
    tanks = {
        item["name"] for item in roles if item["role"] == "坦克"
    }
    boss_melee_by_tank = Counter()
    for event in parsed_damage:
        if (
            start_sec <= event["sec"] <= end_sec
            and event["source"] == "桑夫·塔斯达尔"
            and event["spell"] == "近战"
            and event["target"] in tanks
        ):
            boss_melee_by_tank[event["target"]] += event["damage"]
    boss_tank = (
        max(boss_melee_by_tank, key=boss_melee_by_tank.get)
        if boss_melee_by_tank else None
    )

    def target_actions(target_name):
        actions = [
            {
                "source": event["source"],
                "sec": event["sec"],
                "line": event["line"],
            }
            for event in parsed_damage
            if event["source"] in roster
            and target_name in row_bodies.get(event["line"], "")
        ]
        for row in sanf_rows:
            cast = re.match(
                r"(.+?)对" + re.escape(target_name) + r"(?: \(桑夫·塔斯达尔\))?施放了",
                row["body"],
            )
            if cast and normalize_unit(cast.group(1)) in roster:
                actions.append({
                    "source": normalize_unit(cast.group(1)),
                    "sec": row["sec"],
                    "line": row["line"],
                })
        unique = {}
        for action in actions:
            unique[(action["source"], action["sec"], action["line"])] = action
        return sorted(unique.values(), key=lambda item: (item["sec"], item["line"]))

    mass_moments = []
    for row in sanf_rows:
        mass_gain = re.match(r"(.+?)受到了裂隙诅咒效果的影响", row["body"])
        mass_immune = row["body"].startswith("桑夫·塔斯达尔的裂隙诅咒施放失败。")
        if mass_gain or mass_immune:
            if not mass_moments or row["sec"] - mass_moments[-1] > 0.5:
                mass_moments.append(row["sec"])

    removals = []
    casts = []
    focused_effects = {"裂隙诅咒", "裂隙纠缠"}
    for row in sanf_rows:
        remove = re.match(r"(.+?)的(.+?)被移除了", row["body"])
        if remove and remove.group(2) in focused_effects:
            removals.append({
                "sec": row["sec"],
                "target": normalize_unit(remove.group(1)),
                "effect": remove.group(2),
            })
        cast = re.match(
            r"(.+?)对(.+?)施放了(" + "|".join(DISPEL_SPELLS) + r")",
            row["body"],
        )
        if cast:
            casts.append({
                "sec": row["sec"],
                "ts": row["ts"],
                "caster": normalize_unit(cast.group(1)),
                "target": normalize_unit(cast.group(2)),
                "spell": cast.group(3),
            })

    wrong_dispels = []
    mass_curse_dispels = []
    seen = set()
    for cast in casts:
        key = (cast["ts"], cast["caster"], cast["target"], cast["spell"])
        if key in seen:
            continue
        seen.add(key)
        removed = next((
            item for item in removals
            if abs(item["sec"] - cast["sec"]) <= 0.2
            and item["target"] == cast["target"]
        ), None)
        if not removed:
            continue
        wave = sum(1 for moment in mass_moments if moment <= removed["sec"])
        if removed["effect"] == "裂隙诅咒":
            mass_curse_dispels.append({
                "sec": cast["sec"],
                "offset": round(cast["sec"] - start_sec, 3),
                "caster": cast["caster"],
                "target": cast["target"],
                "spell": cast["spell"],
                "wave": wave,
            })
            continue
        wrong_dispels.append({
            "offset": round(cast["sec"] - start_sec, 3),
            "caster": cast["caster"],
            "target": cast["target"],
            "spell": cast["spell"],
            "removed": removed["effect"],
            "reason": "单点效果用于攻击德莱尼虚无行者，不应解除",
        })

    voidwalker_name = "德莱尼虚无行者"
    rift_attacks = target_actions(voidwalker_name)
    voidwalker_deaths = [
        row["sec"] for row in sanf_rows
        if row["body"] == voidwalker_name + "死亡了。"
    ]
    voidwalker_windows = []
    previous_death = start_sec
    for death_sec in voidwalker_deaths:
        mentions = [
            row["sec"] for row in sanf_rows
            if previous_death < row["sec"] <= death_sec
            and voidwalker_name in row["body"]
        ]
        if mentions:
            voidwalker_windows.append((min(mentions), death_sec))
        previous_death = death_sec
    remaining_mentions = [
        row["sec"] for row in sanf_rows
        if previous_death < row["sec"] <= end_sec
        and voidwalker_name in row["body"]
    ]
    if remaining_mentions:
        voidwalker_windows.append((min(remaining_mentions), end_sec))

    entanglement_gains = []
    for row in sanf_rows:
        gain = re.match(r"(.+?)受到了裂隙纠缠效果的影响", row["body"])
        if gain:
            entanglement_gains.append({
                "player": normalize_unit(gain.group(1)),
                "sec": row["sec"],
                "ts": row["ts"],
            })
    entanglement_issues = []
    for index, gain in enumerate(entanglement_gains):
        next_same_gain = next((
            item["sec"] for item in entanglement_gains[index + 1:]
            if item["player"] == gain["player"]
        ), end_sec)
        fade_candidates = []
        for row in sanf_rows:
            if not (gain["sec"] <= row["sec"] <= next_same_gain):
                continue
            if row["body"] == "裂隙纠缠效果从%s身上消失。" % gain["player"]:
                fade_candidates.append(row["sec"])
            if row["body"].startswith(gain["player"] + "的裂隙纠缠被移除了"):
                fade_candidates.append(row["sec"])
        window_end = min(fade_candidates + [next_same_gain, end_sec])
        available_windows = [
            (max(gain["sec"], left), min(window_end, right))
            for left, right in voidwalker_windows
            if min(window_end, right) > max(gain["sec"], left)
        ]
        first_attack = next((
            event for event in rift_attacks
            if event["source"] == gain["player"]
            and any(left <= event["sec"] <= right for left, right in available_windows)
        ), None)
        if first_attack is None:
            observation = max(0, window_end - max(gain["sec"], start_sec))
            available_duration = sum(right - left for left, right in available_windows)
            if gain["player"] == boss_tank:
                result = "接首领坦克豁免，不检查虚无行者"
                counted_error = False
            elif available_duration <= 0:
                result = "场上无德莱尼虚无行者，不计错"
                counted_error = False
            elif available_duration < 3.0:
                result = "小怪可攻击窗口不足，不计错"
                counted_error = False
            else:
                result = "未攻击德莱尼虚无行者"
                counted_error = True
            entanglement_issues.append({
                "player": gain["player"],
                "applied_offset": round(gain["sec"] - start_sec, 3),
                "window": round(observation, 3),
                "add_window": round(available_duration, 3),
                "result": result,
                "counted_error": counted_error,
            })

    tracker_name = "德莱尼裂隙追踪者"
    tracker_deaths = [
        row for row in sanf_rows
        if row["body"] == tracker_name + "死亡了。"
    ]
    tracker_waves = []
    previous_death = start_sec
    for wave, death in enumerate(tracker_deaths, 1):
        mentions = [
            row for row in sanf_rows
            if previous_death < row["sec"] <= death["sec"]
            and tracker_name in row["body"]
        ]
        first = mentions[0]["sec"] if mentions else death["sec"]
        duration = death["sec"] - first
        tracker_waves.append({
            "wave": wave,
            "first_offset": round(first - start_sec, 3),
            "death_offset": round(death["sec"] - start_sec, 3),
            "duration": round(duration, 3),
            "result": "未及时（超过20秒）" if duration > 20.0 else "20秒内击杀",
        })
        previous_death = death["sec"]

    player_deaths = []
    for row in sanf_rows:
        death = re.match(r"(.+?)死亡了。", row["body"])
        if death and normalize_unit(death.group(1)) in roster:
            player_deaths.append({
                "player": normalize_unit(death.group(1)),
                "sec": row["sec"],
            })
    feedback_casts = [
        row for row in sanf_rows
        if row["body"] == "桑夫·塔斯达尔开始施放裂隙回馈。"
    ]
    rift_feedbacks = []
    rift_feedback_death_issues = []
    for cast in feedback_casts:
        targets = set()
        damaged_players = []
        total_damage = 0
        hit_moments = []
        for row in sanf_rows:
            if not (cast["sec"] <= row["sec"] <= cast["sec"] + 5.0):
                continue
            hit = re.match(
                r"桑夫·塔斯达尔的裂隙回馈击中(.+?)造成(\d+)点奥术伤害",
                row["body"],
            )
            resisted = re.match(
                r"桑夫·塔斯达尔的裂隙回馈被(.+?)抵抗了",
                row["body"],
            )
            if hit:
                target = normalize_unit(hit.group(1))
                if target in roster:
                    targets.add(target)
                    damage = int(hit.group(2))
                    total_damage += damage
                    if damage > 0:
                        damaged_players.append({
                            "player": target,
                            "damage": damage,
                        })
                    hit_moments.append(row["sec"])
            elif resisted:
                target = normalize_unit(resisted.group(1))
                if target in roster:
                    targets.add(target)
                    hit_moments.append(row["sec"])
        last_hit = max(hit_moments) if hit_moments else cast["sec"]
        deaths = sorted({
            item["player"] for item in player_deaths
            if cast["sec"] <= item["sec"] <= last_hit + 0.2
            and item["player"] in targets
        })
        latest_wave_sec = max(
            [moment for moment in mass_moments if moment <= cast["sec"]]
            or [start_sec]
        )
        for victim in deaths:
            relevant_dispels = [
                item for item in mass_curse_dispels
                if item["target"] == victim
                and latest_wave_sec <= item["sec"] <= last_hit + 0.2
            ]
            dispel = max(
                relevant_dispels, key=lambda item: item["sec"]
            ) if relevant_dispels else None
            damage = next((
                item["damage"] for item in damaged_players
                if item["player"] == victim
            ), 0)
            rift_feedback_death_issues.append({
                "victim": victim,
                "responsible": dispel["caster"] if dispel else victim,
                "feedback_offset": round(cast["sec"] - start_sec, 3),
                "damage": damage,
                "dispeller": dispel["caster"] if dispel else None,
                "dispel_spell": dispel["spell"] if dispel else None,
                "dispel_offset": dispel["offset"] if dispel else None,
                "reason": (
                    "%s在裂隙回馈前解除了其裂隙诅咒" % dispel["caster"]
                    if dispel
                    else "未找到驱散记录，责任归死者本人"
                ),
            })
        rift_feedbacks.append({
            "cast_offset": round(cast["sec"] - start_sec, 3),
            "logged_targets": len(targets),
            "damaged_players": damaged_players,
            "damage": total_damage,
            "deaths": deaths,
        })

    hatred_casts = [
        row for row in sanf_rows
        if row["body"] == "桑夫·塔斯达尔开始施放仇恨溢出。"
    ]
    overflowing_hatreds = []
    for cast in hatred_casts:
        resolution_rows = [
            row for row in sanf_rows
            if cast["sec"] <= row["sec"] <= cast["sec"] + 6.5
            and "桑夫·塔斯达尔的仇恨溢出" in row["body"]
        ]
        nearby_deaths = sorted({
            item["player"] for item in player_deaths
            if cast["sec"] + 5.0 <= item["sec"] <= cast["sec"] + 6.5
        })
        hit_events = [
            event for event in parsed_damage
            if cast["sec"] <= event["sec"] <= cast["sec"] + 6.5
            and event["source"] == "桑夫·塔斯达尔"
            and event["spell"] == "仇恨溢出"
            and event["target"] in roster
        ]
        direct_deaths = sorted({
            event["target"] for event in hit_events
            if any(
                death["player"] == event["target"]
                and event["sec"] <= death["sec"] <= event["sec"] + 0.2
                for death in player_deaths
            )
        })
        overflowing_hatreds.append({
            "cast_offset": round(cast["sec"] - start_sec, 3),
            "resolution": (
                "；".join(row["body"] for row in resolution_rows)
                if resolution_rows else "未记录命中、抵抗或免疫"
            ),
            "deaths": nearby_deaths,
            "direct_deaths": direct_deaths,
            "counted_error": bool(direct_deaths),
        })

    shadow_name = "失落暗影的德莱尼人"
    shadow_deaths = [
        row for row in sanf_rows
        if row["body"] == shadow_name + "死亡了。"
    ]
    death_clusters = []
    for death in shadow_deaths:
        if not death_clusters or death["sec"] - death_clusters[-1][-1]["sec"] > 0.5:
            death_clusters.append([death])
        else:
            death_clusters[-1].append(death)
    shadow_actions = target_actions(shadow_name)
    shadow_attackers = sorted(
        item["name"] for item in roles
        if item["class"] == "术士"
        or (item["class"] == "牧师" and item["role"] == "法术远程")
    )
    shadow_waves = []
    previous_cluster_end = start_sec
    for wave, cluster in enumerate(death_clusters, 1):
        cluster_end = cluster[-1]["sec"]
        valid_mentions = [
            row for row in sanf_rows
            if previous_cluster_end < row["sec"] <= cluster_end
            and shadow_name in row["body"]
            and (
                row["body"].startswith(shadow_name)
                or any(action["line"] == row["line"] for action in shadow_actions)
            )
        ]
        first = valid_mentions[0]["sec"] if valid_mentions else cluster[0]["sec"]
        timely = []
        delayed = []
        missed = []
        for player in shadow_attackers:
            first_attack = next((
                event for event in shadow_actions
                if event["source"] == player
                and first <= event["sec"] <= cluster_end
            ), None)
            if first_attack is None:
                missed.append(player)
            else:
                delay = first_attack["sec"] - first
                if delay <= 3.0:
                    timely.append("%s %.1f秒" % (player, delay))
                else:
                    delayed.append("%s %.1f秒" % (player, delay))
        shadow_waves.append({
            "wave": wave,
            "first_offset": round(first - start_sec, 3),
            "death_offset": round(cluster_end - start_sec, 3),
            "count": len(cluster),
            "timely": timely,
            "delayed": delayed,
            "missed": missed,
        })
        previous_cluster_end = cluster_end

    large_add_transformations = []
    for wipe_attempt, first_start_sec, first_rows in wipe_rows:
        rift_element_observation = next((
            row for row in first_rows
            if "裂隙元素" in row["body"]
            and "形成裂隙元素" not in row["body"]
        ), None)
        if not rift_element_observation:
            continue
        formation_cast = next((
            row for row in reversed(first_rows)
            if row["sec"] <= rift_element_observation["sec"]
            and row["body"] == "德莱尼裂隙行者开始施放形成裂隙元素。"
        ), None)
        melee_players = sorted(
            item["name"] for item in roles
            if item["role"] == "物理近战"
        )
        large_add_transformations.append({
            "attempt": wipe_attempt["attempt"],
            "cast_offset": (
                round(formation_cast["sec"] - first_start_sec, 3)
                if formation_cast else None
            ),
            "observed_offset": round(
                rift_element_observation["sec"] - first_start_sec, 3
            ),
            "result": "德莱尼裂隙行者成功形成裂隙元素",
            "responsible": melee_players,
            "error_rule": "所有物理近战各计1次",
        })

    return {
        "start": start,
        "end": end,
        "attempts": attempts,
        "mass_curse_waves": [
            {"wave": index + 1, "offset": round(moment - start_sec, 3)}
            for index, moment in enumerate(mass_moments)
        ],
        "wrong_dispels": wrong_dispels,
        "mass_curse_dispels": mass_curse_dispels,
        "rift_feedback_death_issues": rift_feedback_death_issues,
        "boss_tank": boss_tank,
        "voidwalker_name": voidwalker_name,
        "voidwalker_windows": [{
            "first_offset": round(left - start_sec, 3),
            "end_offset": round(right - start_sec, 3),
        } for left, right in voidwalker_windows],
        "entanglement_issues": entanglement_issues,
        "large_add_transformations": large_add_transformations,
        "tracker_waves": tracker_waves,
        "rift_feedbacks": rift_feedbacks,
        "overflowing_hatreds": overflowing_hatreds,
        "shadow_rule": "首次可见后3秒内首次造成有效伤害视为及时；无GUID，同批连续死亡按0.5秒聚类",
        "shadow_waves": shadow_waves,
    }


def analyze_consumables(rows, roster, parsed_damage, roles):
    gains = defaultdict(list)
    losses = defaultdict(list)
    raid_start_sec, raid_end_sec = seconds(RAID_START), seconds(RAID_END)
    for row in rows:
        gain = re.match(r"(.+?)获得了(.+?(?:药剂|合剂))的效果", row["body"])
        if gain:
            player = normalize_unit(gain.group(1))
            if player in roster:
                gains[player].append({"name": gain.group(2), "ts": row["ts"], "sec": row["sec"], "line": row["line"]})
        loss = re.match(r"(.+?(?:药剂|合剂))效果从(.+?)身上消失", row["body"])
        if loss:
            player = normalize_unit(loss.group(2))
            if player in roster:
                losses[player].append({"name": loss.group(1), "ts": row["ts"], "sec": row["sec"], "line": row["line"]})

    deaths = defaultdict(list)
    for row in rows:
        death = re.match(r"(.+?)死亡了。", row["body"])
        if death:
            player = normalize_unit(death.group(1))
            if player in roster and raid_start_sec <= row["sec"] <= raid_end_sec:
                deaths[player].append({"ts": row["ts"], "sec": row["sec"], "line": row["line"]})

    windows = combat_windows(parsed_damage, roster)
    expiration_issues = []
    for player in sorted(roster):
        player_gains = sorted(gains[player], key=lambda item: item["sec"])
        for loss in sorted(losses[player], key=lambda item: item["sec"]):
            if not (raid_start_sec <= loss["sec"] <= raid_end_sec) or loss["name"] == "屠魔药剂":
                continue
            next_gain = next((item for item in player_gains if item["name"] == loss["name"] and item["sec"] >= loss["sec"]), None)
            delay = next_gain["sec"] - loss["sec"] if next_gain and next_gain["sec"] <= raid_end_sec else None
            gap_end_sec = min(next_gain["sec"] if delay is not None else raid_end_sec, left_at(player))
            combat_delay = combat_overlap_duration(loss["sec"], gap_end_sec, windows)
            if combat_delay > CONSUMABLE_GAP_THRESHOLD:
                expiration_issues.append({
                    "player": player,
                    "name": loss["name"],
                    "expired": loss["ts"],
                    "regained": next_gain["ts"] if delay is not None else None,
                    "delay": round(delay, 2) if delay is not None else None,
                    "combat_delay": round(combat_delay, 2),
                })

    death_issues = []
    for player in sorted(roster):
        player_gains = sorted(gains[player], key=lambda item: item["sec"])
        regular_gains = [item for item in player_gains if "药剂" in item["name"] and item["name"] != "屠魔药剂"]
        first_death_sec = deaths[player][0]["sec"] if deaths[player] else raid_end_sec
        baseline_profile = set(item["name"] for item in regular_gains if item["sec"] < first_death_sec)
        for death_index, death in enumerate(deaths[player]):
            current_window = next((window for window in windows if window[0] <= death["sec"] <= window[1] + 1.0), None)
            after_sec = current_window[1] if current_window else death["sec"]
            next_pull = next((window[0] for window in windows if window[0] > after_sec + 1.0), None)
            if next_pull is None or next_pull > left_at(player):
                continue
            next_death = deaths[player][death_index + 1]["sec"] if death_index + 1 < len(deaths[player]) else None
            if next_death is not None and next_death < next_pull:
                continue
            known_profile = baseline_profile
            before_pull = [item for item in regular_gains if death["sec"] < item["sec"] <= next_pull]
            regained_names = set(item["name"] for item in before_pull)
            missing = sorted(known_profile - regained_names)
            long_missing = []
            missing_combat_durations = {}
            for name in missing:
                next_gain = next((
                    item for item in regular_gains
                    if item["name"] == name and item["sec"] > next_pull
                ), None)
                gap_end = next_gain["sec"] if next_gain else raid_end_sec
                combat_duration = combat_overlap_duration(next_pull, gap_end, windows)
                if combat_duration > CONSUMABLE_GAP_THRESHOLD:
                    long_missing.append(name)
                    missing_combat_durations[name] = round(combat_duration, 2)
            unknown_combat_duration = 0
            if not known_profile and not before_pull:
                next_regular_gain = next((
                    item for item in regular_gains if item["sec"] > next_pull
                ), None)
                gap_end = next_regular_gain["sec"] if next_regular_gain else raid_end_sec
                unknown_combat_duration = combat_overlap_duration(next_pull, gap_end, windows)
            if long_missing or unknown_combat_duration > CONSUMABLE_GAP_THRESHOLD:
                death_issues.append({
                    "player": player,
                    "death": death["ts"],
                    "next_pull": next(row["ts"] for row in rows if row["sec"] >= next_pull),
                    "known_profile": sorted(known_profile),
                    "regained_before_pull": sorted(regained_names),
                    "missing": long_missing,
                    "missing_combat_durations": missing_combat_durations,
                    "unknown_combat_duration": round(unknown_combat_duration, 2),
                    "note": (
                        "缺少已知常驻药剂超过60秒战斗时间"
                        if known_profile else
                        "初始药名不可见，下次开怪后超过60秒战斗时间未见常驻药剂"
                    ),
                })

    demon_bosses = [
        (boss,) + encounter_window(boss)
        for boss in DEMON_SLAYING_BOSSES
    ]
    melee_players = sorted(
        item["name"] for item in roles
        if item["role"] == "物理近战" and (
            item["class"] in ("战士", "盗贼", "猎人")
            or item["class"] == "德鲁伊"
        )
    )
    role_by_name = {item["name"]: item for item in roles}
    demon_events = defaultdict(list)
    for row in rows:
        gain = re.match(r"(.+?)获得了屠魔药剂的效果", row["body"])
        if gain:
            player = normalize_unit(gain.group(1))
            if player in melee_players:
                demon_events[player].append(("gain", row["sec"], row["ts"]))
        loss = re.match(r"屠魔药剂效果从(.+?)身上消失", row["body"])
        if loss:
            player = normalize_unit(loss.group(1))
            if player in melee_players:
                demon_events[player].append(("loss", row["sec"], row["ts"]))
    demon_slaying_issues = []
    for boss, start, end in demon_bosses:
        start_sec, end_sec = seconds(start), seconds(end)
        for player in melee_players:
            events = sorted(demon_events[player], key=lambda item: item[1])
            latest = next((item for item in reversed(events) if item[1] <= start_sec), None)
            if latest and latest[0] == "gain":
                continue
            next_gain = next((item for item in events if start_sec < item[1] <= end_sec and item[0] == "gain"), None)
            demon_slaying_issues.append({
                "boss": boss,
                "boss_start": start,
                "player": player,
                "class": role_by_name[player]["class"],
                "regained": next_gain[2] if next_gain else None,
                "delay": round(next_gain[1] - start_sec, 2) if next_gain else None,
            })

    return {
        "assumption": "开打时默认全员常驻药剂与合剂齐全；另检查近战职业在指定恶魔Boss开打瞬间是否有屠魔药剂。",
        "gap_threshold": CONSUMABLE_GAP_THRESHOLD,
        "expiration_issues": expiration_issues,
        "death_issues": death_issues,
        "demon_slaying_melee": melee_players,
        "demon_slaying_issues": demon_slaying_issues,
    }


def analyze_narmuun(rows, roster, parsed_damage, roles):
    start, end = encounter_window("守护者纳尔穆恩")
    start_sec, end_sec = seconds(start), seconds(end)
    tanks = {
        item["name"] for item in roles if item["role"] == "坦克"
    }

    preparation = []
    for label, aura in (("火炕", "防护火焰"), ("冰冻符文", "火焰防护")):
        missing = []
        for player in sorted(roster):
            if label == "火炕" and player in tanks:
                continue
            state = None
            for row in rows:
                if row["sec"] > start_sec:
                    break
                gain = re.match(r"(.+?)获得了" + re.escape(aura) + r"的效果", row["body"])
                if gain and normalize_unit(gain.group(1)) == player:
                    state = "gain"
                loss = re.match(re.escape(aura) + r"效果从(.+?)身上消失", row["body"])
                if loss and normalize_unit(loss.group(1)) == player:
                    state = "loss"
            if state != "gain":
                missing.append(player)
        preparation.append({
            "item": label,
            "log_aura": aura,
            "missing": missing,
            "status": "有问题" if missing else "无问题",
        })

    moon_color = {}
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        applied = re.match(r"(.+?)受到了(红月|蓝月)效果", row["body"])
        if applied:
            moon_color[normalize_unit(applied.group(1))] = applied.group(2)
    moon_outgoing = defaultdict(lambda: {"hits": 0, "damage": 0})
    for event in parsed_damage:
        if not (start_sec <= event["sec"] <= end_sec):
            continue
        if event["source"] != "守护者纳尔穆恩" or event["spell"] not in ("红月", "蓝月"):
            continue
        player = event["target"]
        assigned = moon_color.get(player)
        if assigned and event["spell"] != assigned and event["damage"] > 0:
            # The mechanic is reciprocal: damage received from the opposite moon
            # is the same amount this player dealt to nearby opposite-color players.
            moon_outgoing[player]["hits"] += 1
            moon_outgoing[player]["damage"] += event["damage"]
    boss_melee_by_tank = Counter()
    for event in parsed_damage:
        if (
            start_sec <= event["sec"] <= end_sec
            and event["source"] == "守护者纳尔穆恩"
            and event["spell"] == "近战"
            and event["target"] in tanks
        ):
            boss_melee_by_tank[event["target"]] += event["damage"]
    main_tank = (
        max(boss_melee_by_tank, key=boss_melee_by_tank.get)
        if boss_melee_by_tank else None
    )
    moon_outgoing_by_player = [{
        "player": player,
        "assigned": moon_color[player],
        "damaged_group": "蓝月组" if moon_color[player] == "红月" else "红月组",
        "hits": values["hits"],
        "damage": values["damage"],
        "is_main_tank": player == main_tank,
        "is_error": (
            player != main_tank
            and values["damage"] > MOON_OUTGOING_ERROR_THRESHOLD
        ),
    } for player, values in sorted(
        moon_outgoing.items(), key=lambda item: (-item[1]["damage"], item[0])
    )]

    applications = []
    removals = []
    siphon_damage = []
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        gain = re.match(r"(.+?)受到了鲜血虹吸效果", row["body"])
        if gain:
            applications.append({"target": gain.group(1), "sec": row["sec"], "ts": row["ts"]})
        removed = re.match(r"(.+?)的鲜血虹吸被移除了", row["body"])
        if removed:
            removals.append({"target": removed.group(1), "sec": row["sec"], "ts": row["ts"]})
        damage = re.match(r"守护者纳尔穆恩的鲜血虹吸使(.+?)受到了(\d+)点", row["body"])
        if damage:
            siphon_damage.append({"target": damage.group(1), "sec": row["sec"], "damage": int(damage.group(2))})
    curse_issues = []
    for index, application in enumerate(applications):
        next_same = next((
            item["sec"] for item in applications[index + 1:]
            if item["target"] == application["target"]
        ), end_sec)
        removal = next((
            item for item in removals
            if item["target"] == application["target"]
            and application["sec"] <= item["sec"] < next_same
        ), None)
        right = removal["sec"] if removal else next_same
        damage_events = [
            item for item in siphon_damage
            if item["target"] == application["target"] and application["sec"] <= item["sec"] <= right
        ]
        if damage_events or removal is None:
            curse_issues.append({
                "target": normalize_unit(application["target"]),
                "applied_offset": round(application["sec"] - start_sec, 2),
                "removed_offset": round(removal["sec"] - start_sec, 2) if removal else None,
                "delay": round(removal["sec"] - application["sec"], 2) if removal else None,
                "ticks": len(damage_events),
                "damage": sum(item["damage"] for item in damage_events),
            })

    wild_druids = {
        item["name"] for item in roles
        if item["class"] == "德鲁伊" and item["role"] in ("坦克", "物理近战")
    }
    decursers = sorted(
        name for name, class_name in PLAYER_CLASSES.items()
        if name in roster and class_name in ("法师", "德鲁伊") and name not in wild_druids
    )
    decurse_counts = Counter()
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        cast = re.match(r"(.+?)对.+?施放了(解除诅咒|解除次级诅咒)", row["body"])
        if cast:
            caster = normalize_unit(cast.group(1))
            if caster in decursers:
                decurse_counts[caster] += 1

    raw_owl_starts = sorted(set(
        row["sec"] for row in rows
        if start_sec <= row["sec"] <= end_sec
        and re.match(r"红枭受到了红色猫头鹰光环效果", row["body"])
    ))
    owl_starts = []
    for value in raw_owl_starts:
        if not owl_starts or value - owl_starts[-1] > 1.0:
            owl_starts.append(value)
    owl_issues = []
    periodic_spells = {
        "重伤", "痛苦诅咒", "腐蚀术", "点燃", "割裂", "致命毒药 V",
        "献祭陷阱效果", "艾林寄生", "月火术", "虫群",
    }
    for wave_index, wave_start in enumerate(owl_starts):
        wave_end = owl_starts[wave_index + 1] if wave_index + 1 < len(owl_starts) else end_sec
        deaths = sorted(
            row["sec"] for row in rows
            if wave_start <= row["sec"] < wave_end
            and row["body"] in ("红枭死亡了。", "蓝枭死亡了。")
        )
        final_burn_start = deaths[-1] - 10.0 if deaths else wave_end
        for target in ("红枭", "蓝枭"):
            target_deaths = sorted(
                row["sec"] for row in rows
                if wave_start <= row["sec"] < wave_end and row["body"] == target + "死亡了。"
            )
            segment_start = wave_start
            for death_index, death_sec in enumerate(target_deaths, 1):
                damage_events = [
                    event for event in parsed_damage
                    if segment_start <= event["sec"] <= death_sec
                    and event["target"] == target and event["source"] in roster
                ]
                total_damage = sum(event["damage"] for event in damage_events)
                running = 0
                threshold_index = None
                for event_index, event in enumerate(damage_events):
                    running += event["damage"]
                    if threshold_index is None and running >= total_damage * 0.95:
                        threshold_index = event_index
                offenders = Counter()
                offender_damage = Counter()
                if threshold_index is not None:
                    for event in damage_events[threshold_index + 1:]:
                        if event["sec"] >= final_burn_start:
                            continue
                        if event["spell"] in periodic_spells:
                            continue
                        offenders[event["source"]] += 1
                        offender_damage[event["source"]] += event["damage"]
                for player in sorted(offenders, key=lambda name: (-offender_damage[name], name)):
                    owl_issues.append({
                        "wave": wave_index + 1,
                        "owl": target + "%d" % death_index,
                        "player": player,
                        "hits": offenders[player],
                        "damage": offender_damage[player],
                        "death_offset": round(death_sec - start_sec, 2),
                        "method": "同名单位无GUID，按每次死亡间的累计伤害反推5%阶段",
                    })
                segment_start = death_sec + 0.001

    return {
        "boss": "守护者纳尔穆恩",
        "preparation": preparation,
        "moon_outgoing_by_player": moon_outgoing_by_player,
        "moon_error_threshold": MOON_OUTGOING_ERROR_THRESHOLD,
        "moon_exempt_main_tank": main_tank,
        "moon_main_tank_method": "纳尔穆恩战中承受Boss近战伤害最高的坦克",
        "moon_boss_melee_by_tank": dict(sorted(boss_melee_by_tank.items())),
        "moon_method": "红蓝月为双向等额互伤；日志记录的个人异色承伤，按机制等额换算为该玩家对别人造成的伤害。",
        "curse_issues": curse_issues,
        "decurse_counts": [{
            "player": name,
            "class": "法师" if PLAYER_CLASSES[name] == "法师" else "德鲁伊",
            "count": decurse_counts[name],
        } for name in decursers],
        "owl_issues": owl_issues,
    }


def analyze_intagos(rows, roster, parsed_damage, dps_players, roles):
    start, end = encounter_window("魔网观察者因塔苟斯")
    start_sec, end_sec = seconds(start), seconds(end)
    dps_by_name = {item["name"]: item for item in dps_players}
    role_by_name = {item["name"]: item for item in roles}

    # Only the four unowned seekers present at the pull are the initial add pack.
    # Boss-owned seekers and whelps are later summons and do not extend this check.
    initial_add_deaths = [
        row for row in rows
        if start_sec <= row["sec"] <= end_sec
        and row["body"] == "魔鳞魔网搜寻者死亡了。"
    ]
    adds_clear_sec = max(item["sec"] for item in initial_add_deaths) if initial_add_deaths else start_sec
    early_boss_damage = defaultdict(lambda: {"hits": 0, "damage": 0, "first_sec": None, "spells": Counter()})
    for event in parsed_damage:
        if not (start_sec <= event["sec"] < adds_clear_sec):
            continue
        if event["target"] != "魔网观察者因塔苟斯":
            continue
        player = dps_by_name.get(event["source"])
        role = role_by_name.get(event["source"])
        if not player or not role or role["role"] != "法术远程":
            continue
        item = early_boss_damage[event["source"]]
        item["hits"] += 1
        item["damage"] += event["damage"]
        item["spells"][event["spell"]] += event["damage"]
        if item["first_sec"] is None:
            item["first_sec"] = event["sec"]
    early_casters = [{
        "player": player,
        "class": dps_by_name[player]["class"],
        "first_offset": round(values["first_sec"] - start_sec, 2),
        "hits": values["hits"],
        "damage": values["damage"],
        "spells": values["spells"].most_common(4),
    } for player, values in sorted(
        early_boss_damage.items(), key=lambda item: (-item[1]["damage"], item[0])
    )]

    affinity_schools = {
        "红色亲和": "火焰",
        "绿色亲和": "自然",
        "水晶亲和": "物理",
        "魔力亲和": "奥术",
        "黑色亲和": "暗影",
        "蓝色亲和": "冰霜",
    }
    affinity_capable_classes = {
        "火焰": {"法师", "术士"},
        "自然": {"平衡德", "萨满", "猎人"},
        "物理": {"战士", "盗贼", "野性德", "猎人", "圣骑士"},
        "奥术": {"法师", "平衡德", "猎人"},
        "暗影": {"术士", "牧师"},
        "冰霜": {"法师"},
    }
    affinities = []
    boss_death_sec = next(
        (
            row["sec"] for row in rows
            if start_sec <= row["sec"] <= end_sec + 2
            and row["body"] == "魔网观察者因塔苟斯死亡了。"
        ),
        end_sec,
    )
    for affinity, allowed_school in affinity_schools.items():
        gains = [
            row["sec"] for row in rows
            if start_sec <= row["sec"] <= end_sec
            and re.match(r".+?获得了" + re.escape(affinity) + r"的效果", row["body"])
        ]
        deaths = [
            row["sec"] for row in rows
            if start_sec <= row["sec"] <= boss_death_sec + 2
            and row["body"] == affinity + "死亡了。"
        ]
        if not gains and not deaths:
            continue
        affinity_start = min(gains) if gains else start_sec
        normal_deaths = [death for death in deaths if death <= boss_death_sec]
        count_zero_errors = bool(normal_deaths)
        affinity_end = min(normal_deaths) if normal_deaths else boss_death_sec
        outcome = (
            "亲和被正常击杀，零对应伤害计错"
            if count_zero_errors
            else "以击杀Boss收尾，未打亲和不计错"
        )
        damage_by_player = Counter()
        hits_by_player = Counter()
        for event in parsed_damage:
            if not (affinity_start <= event["sec"] <= affinity_end):
                continue
            if event["target"] != affinity or event["school"] != allowed_school:
                continue
            if event["source"] in roster:
                damage_by_player[event["source"]] += event["damage"]
                hits_by_player[event["source"]] += 1
        capable = []
        if allowed_school is not None:
            for player in roster:
                if role_by_name[player]["role"] == "坦克":
                    continue
                dps_item = dps_by_name.get(player)
                player_class = dps_item["class"] if dps_item else PLAYER_CLASSES.get(player, "未识别")
                if allowed_school == "物理":
                    is_capable = role_by_name[player]["role"] in ("物理近战", "物理远程")
                else:
                    is_capable = player_class in affinity_capable_classes[allowed_school]
                if is_capable:
                    capable.append(player)
        affinities.append({
            "affinity": affinity,
            "allowed_school": allowed_school or "历史未确认",
            "start_offset": round(affinity_start - start_sec, 2),
            "end_offset": round(affinity_end - start_sec, 2),
            "outcome": outcome,
            "count_zero_errors": count_zero_errors,
            "players": [{
                "player": player,
                "class": dps_by_name[player]["class"] if player in dps_by_name else PLAYER_CLASSES.get(player, "未识别"),
                "hits": hits_by_player[player],
                "damage": damage_by_player[player],
                "is_error": hits_by_player[player] == 0 and count_zero_errors,
                "result": (
                    "已攻击"
                    if hits_by_player[player] > 0
                    else "未攻击，计错"
                    if count_zero_errors
                    else "未攻击，Boss击杀收尾不计错"
                ),
            } for player in sorted(capable, key=lambda name: (-damage_by_player[name], name))],
        })

    preparation = []
    missing_frost = []
    for player in sorted(roster):
        if role_by_name[player]["role"] == "坦克":
            continue
        state = None
        for row in rows:
            if row["sec"] > start_sec:
                break
            gain = re.match(r"(.+?)获得了防护冰霜的效果", row["body"])
            if gain and normalize_unit(gain.group(1)) == player:
                state = "gain"
            loss = re.match(r"防护冰霜效果从(.+?)身上消失", row["body"])
            if loss and normalize_unit(loss.group(1)) == player:
                state = "loss"
        if state != "gain":
            missing_frost.append(player)
    preparation.append({
        "item": "冰抗",
        "log_aura": "防护冰霜",
        "missing": missing_frost,
        "status": "有问题" if missing_frost else "无问题",
    })

    applications = []
    removals = []
    decurse_counts = Counter()
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        gain = re.match(r"(.+?)受到了魔鳞诅咒效果", row["body"])
        if gain:
            raw_target = gain.group(1)
            target = normalize_unit(raw_target)
            target_role = role_by_name.get(target)
            needs_mana = bool(target_role and not (
                target_role["class"] in ("战士", "盗贼")
                or (
                    target_role["class"] == "德鲁伊"
                    and target_role["role"] in ("坦克", "物理近战")
                )
            ))
            if target in roster and needs_mana and (raw_target == target or raw_target in ("你", "你自己")):
                applications.append({"target": target, "sec": row["sec"]})
        removed = re.match(r"(.+?)的魔鳞诅咒被移除了", row["body"])
        if removed:
            target = normalize_unit(removed.group(1))
            if target in roster:
                removals.append({"target": target, "sec": row["sec"]})
        cast = re.match(r"(.+?)对.+?施放了(解除诅咒|解除次级诅咒)", row["body"])
        if cast:
            decurse_counts[normalize_unit(cast.group(1))] += 1

    curse_results = []
    for application in applications:
        removal = next((
            item for item in removals
            if item["target"] == application["target"] and item["sec"] >= application["sec"]
        ), None)
        removed_in_fight = removal is not None and removal["sec"] <= end_sec
        curse_results.append({
            "target": application["target"],
            "applied_offset": round(application["sec"] - start_sec, 2),
            "removed_offset": round(removal["sec"] - start_sec, 2) if removed_in_fight else None,
            "delay": round(removal["sec"] - application["sec"], 2) if removed_in_fight else None,
            "status": "已解除" if removed_in_fight else "战斗结束仍未解除",
        })

    wild_druids = {
        item["name"] for item in roles
        if item["class"] == "德鲁伊" and item["role"] in ("坦克", "物理近战")
    }
    decursers = sorted(
        name for name, class_name in PLAYER_CLASSES.items()
        if name in roster and class_name in ("法师", "德鲁伊") and name not in wild_druids
    )
    return {
        "boss": "魔网观察者因塔苟斯",
        "initial_add_deaths": len(initial_add_deaths),
        "adds_clear_offset": round(adds_clear_sec - start_sec, 2),
        "early_casters": early_casters,
        "affinity_history": {
            "confirmed": "红色=火焰、绿色=自然、水晶=物理、魔力=奥术、黑色=暗影、蓝色=冰霜",
            "class_rule": "火焰和冰霜亲和不统计萨满；自然亲和仍统计萨满",
        },
        "affinities": affinities,
        "preparation": preparation,
        "curse_summary": {
            "applicable_count": len(curse_results),
            "removed_within_10s_count": sum(
                1 for item in curse_results
                if item["status"] == "已解除" and item["delay"] is not None and item["delay"] <= 10
            ),
            "long_count": sum(
                1 for item in curse_results
                if item["status"] == "战斗结束仍未解除"
                or (item["delay"] is not None and item["delay"] > 10)
            ),
            "long_threshold_seconds": 10,
        },
        "curse_results": sorted(
            curse_results,
            key=lambda item: (item["status"] != "战斗结束仍未解除", -(item["delay"] or 0), item["target"]),
        ),
        "decurse_counts": [{
            "player": name,
            "class": "法师" if PLAYER_CLASSES[name] == "法师" else "德鲁伊",
            "count": decurse_counts[name],
        } for name in decursers],
    }


def find_dispel_cast(rows, target, event_sec, window=0.2):
    matches = []
    for row in rows:
        if abs(row["sec"] - event_sec) > window:
            continue
        cast = re.match(
            r"(.+?)对(.+?)施放了(" + "|".join(re.escape(spell) for spell in DISPEL_SPELLS) + r")",
            row["body"],
        )
        if not cast or normalize_unit(cast.group(2)) != target:
            continue
        item = (normalize_unit(cast.group(1)), cast.group(3))
        if item not in matches:
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def analyze_medivh(rows, roster):
    start, end = encounter_window("麦迪文的回响")
    start_sec, end_sec = seconds(start), seconds(end)
    fight_rows = [row for row in rows if start_sec <= row["sec"] <= end_sec]

    casts = []
    for row in fight_rows:
        match = re.match(r"麦迪文的回响开始施放(.+?)[。.]?$", row["body"])
        if match:
            casts.append({"spell": match.group(1).strip(), "sec": row["sec"], "ts": row["ts"]})

    interrupt_spells = ("脚踢", "拳击", "盾击", "法术反制", "大地震击", "沉默", "震荡猛击")
    expected_cast_time = {"冰霜新星": 2.56, "暗影箭": 3.20}
    priority_spells = set(expected_cast_time)
    wrong_interrupts = []
    priority_issues = []
    for index, cast in enumerate(casts):
        next_sec = casts[index + 1]["sec"] if index + 1 < len(casts) else end_sec + 0.2
        failure = next((
            row for row in fight_rows
            if cast["sec"] <= row["sec"] <= next_sec
            and row["body"] == "麦迪文的回响的%s施放失败了" % cast["spell"]
        ), None)
        interrupter = None
        interrupt_spell = None
        if failure:
            candidates = []
            for row in fight_rows:
                if abs(row["sec"] - failure["sec"]) > 0.08:
                    continue
                if "格挡过去" in row["body"] or "施放失败" in row["body"]:
                    continue
                action = re.match(
                    r"(.+?)的(" + "|".join(re.escape(spell) for spell in interrupt_spells)
                    + r").*麦迪文的回响",
                    row["body"],
                )
                if action:
                    item = (normalize_unit(action.group(1)), action.group(2))
                    if item not in candidates:
                        candidates.append(item)
            if len(candidates) == 1:
                interrupter, interrupt_spell = candidates[0]
        elapsed = round(failure["sec"] - cast["sec"], 3) if failure else None
        if cast["spell"] in priority_spells:
            expected = expected_cast_time[cast["spell"]]
            if not failure:
                priority_issues.append({
                    "spell": cast["spell"],
                    "start_offset": round(cast["sec"] - start_sec, 3),
                    "status": "未打断",
                    "interrupter": "未记录",
                    "interrupt_spell": "-",
                    "elapsed": None,
                    "expected": expected,
                })
            elif elapsed < expected - 0.5:
                priority_issues.append({
                    "spell": cast["spell"],
                    "start_offset": round(cast["sec"] - start_sec, 3),
                    "status": "打断过早",
                    "interrupter": interrupter or "无法唯一归因",
                    "interrupt_spell": interrupt_spell or "-",
                    "elapsed": elapsed,
                    "expected": expected,
                })
        elif failure and interrupter and failure["sec"] < end_sec - 0.1:
            wrong_interrupts.append({
                "spell": cast["spell"],
                "start_offset": round(cast["sec"] - start_sec, 3),
                "interrupt_offset": round(failure["sec"] - start_sec, 3),
                "interrupter": interrupter,
                "interrupt_spell": interrupt_spell,
                "elapsed": elapsed,
            })

    doom_dispels = []
    for row in fight_rows:
        removed = re.match(r"(.+?)的麦迪文的灾祸被移除了", row["body"])
        if not removed:
            continue
        target = normalize_unit(removed.group(1))
        dispel = find_dispel_cast(fight_rows, target, row["sec"])
        if dispel:
            doom_dispels.append({
                "target": target,
                "offset": round(row["sec"] - start_sec, 3),
                "dispeller": dispel[0],
                "spell": dispel[1],
            })

    corruption_end = end_sec + 25.0
    corruption_rows = [row for row in rows if start_sec <= row["sec"] <= corruption_end]
    applications = []
    removals = []
    ticks = []
    for row in corruption_rows:
        gain = re.match(r"(.+?)受到了麦迪文的腐化效果", row["body"])
        if gain:
            target = normalize_unit(gain.group(1))
            if target in roster:
                applications.append({"target": target, "sec": row["sec"]})
        loss = re.match(r"麦迪文的腐化效果从(.+?)身上消失", row["body"])
        if loss:
            removals.append({"target": normalize_unit(loss.group(1)), "sec": row["sec"]})
        damage = re.match(r"麦迪文的回响的麦迪文的腐化使(.+?)受到了\d+点", row["body"])
        if damage:
            ticks.append({"target": normalize_unit(damage.group(1)), "sec": row["sec"]})
        self_damage = re.match(r"你受到\d+点暗影伤害（麦迪文的回响的麦迪文的腐化）", row["body"])
        if self_damage:
            ticks.append({"target": LOGGER_NAME, "sec": row["sec"]})

    application_groups = []
    for application in applications:
        if not application_groups or application["sec"] - application_groups[-1][0]["sec"] > 0.2:
            application_groups.append([application])
        else:
            application_groups[-1].append(application)

    boss_applications = []
    transmissions = []
    for group in application_groups:
        group_sec = group[0]["sec"]
        active_before = set()
        for application in applications:
            if application["sec"] >= group_sec - 0.001:
                continue
            removed_after = next((
                removal for removal in removals
                if removal["target"] == application["target"]
                and application["sec"] <= removal["sec"] < group_sec
            ), None)
            if removed_after is None:
                active_before.add(application["target"])
        previously_infected = {
            application["target"]
            for application in applications
            if application["sec"] < group_sec - 0.001
        }
        tick_sources = sorted({
            tick["target"] for tick in ticks
            if tick["target"] in previously_infected and abs(tick["sec"] - group_sec) <= 0.2
        })
        sources = tick_sources or sorted(active_before)
        if not sources:
            boss_applications.append({
                "offset": round(group_sec - start_sec, 3),
                "targets": sorted(item["target"] for item in group),
            })
            continue
        transmissions.append({
            "offset": round(group_sec - start_sec, 3),
            "sources": sources,
            "targets": sorted(item["target"] for item in group),
            "unique_source": len(sources) == 1,
        })

    corruption_dispels = []
    for removal in removals:
        dispel = find_dispel_cast(corruption_rows, removal["target"], removal["sec"])
        if dispel:
            corruption_dispels.append({
                "target": removal["target"],
                "offset": round(removal["sec"] - start_sec, 3),
                "dispeller": dispel[0],
                "spell": dispel[1],
            })

    return {
        "start": start,
        "end": end,
        "language_curse": {
            "spell_id": 11719,
            "rank": 2,
            "max_rank": 2,
            "is_max_rank": True,
            "evidence": "高级战斗日志 AURA_CAST 记录法术ID 11719；该ID为语言诅咒（等级2）",
        },
        "interrupt_rule": "冰霜新星和暗影箭应在读条最后0.5秒内打断；其他技能不应打断",
        "wrong_interrupts": wrong_interrupts,
        "priority_interrupt_issues": priority_issues,
        "doom_dispels": doom_dispels,
        "corruption_boss_applications": boss_applications,
        "corruption_transmissions": transmissions,
        "corruption_dispels": corruption_dispels,
        "corruption_attribution_limit": "每次无人持有腐化时出现的首名感染者视为Boss主动点名；下一次Boss点名前的新增感染者全部视为前一批感染者传播。普通日志不记录精确传播源，按同期腐化跳伤者列候选，多个候选时不强行唯一归因。",
    }


def analyze_king(rows, roster, parsed_damage, roles):
    attempts = [dict(item) for item in ATTEMPTS["国王（国际象棋）"]]

    all_start = seconds(attempts[0]["start"])
    combat_end = seconds(attempts[-1]["end"])
    all_end = combat_end + 1.0
    king_rows = [row for row in rows if all_start <= row["sec"] <= all_end]
    combat_rows = [row for row in king_rows if row["sec"] <= combat_end]

    first_start_sec = seconds(attempts[0]["start"])
    bishop_fear_row = next((
        row for row in king_rows
        if row["body"].startswith("干枯的主教的恐惧")
    ), None)
    bishop_fear_sec = bishop_fear_row["sec"] if bishop_fear_row else None
    ranged = sorted(
        item["name"] for item in roles
        if item["role"] in ("物理远程", "法术远程")
    )
    bishop_contribution = defaultdict(lambda: {"hits": 0, "damage": 0})
    if bishop_fear_sec is not None:
        for event in parsed_damage:
            if (
                first_start_sec <= event["sec"] <= bishop_fear_sec
                and event["target"] == "干枯的主教"
                and event["source"] in ranged
            ):
                bishop_contribution[event["source"]]["hits"] += 1
                bishop_contribution[event["source"]]["damage"] += event["damage"]
    bishop_fear_affected = sorted(set(
        normalize_unit(match.group(1))
        for row in king_rows
        for match in [re.match(r"(.+?)受到了恐惧效果的影响", row["body"])]
        if match
        and bishop_fear_sec is not None
        and bishop_fear_sec <= row["sec"] <= bishop_fear_sec + 1.0
        and normalize_unit(match.group(1)) in roster
    ))
    first_attempt_bishop_fear = {
        "target": "干枯的主教",
        "status": "日志未记录恐惧，无此项问题" if bishop_fear_sec is None else "记录到恐惧",
        "fear_offset": (
            round(bishop_fear_sec - first_start_sec, 3)
            if bishop_fear_sec is not None else None
        ),
        "affected_count": len(bishop_fear_affected),
        "affected": bishop_fear_affected,
        "ranged_results": [{
            "player": player,
            "hits": bishop_contribution[player]["hits"],
            "damage": bishop_contribution[player]["damage"],
            "is_error": (
                bishop_fear_sec is not None
                and bishop_contribution[player]["hits"] == 0
            ),
        } for player in ranged] if bishop_fear_sec is not None else [],
        "ranged_noncontributors": [
            player for player in ranged
            if bishop_fear_sec is not None
            and bishop_contribution[player]["hits"] == 0
        ] if bishop_fear_sec is not None else [],
    }
    role_by_name = {item["name"]: item["role"] for item in roles}
    opening_add_specs = (
        ("干枯的主教", "远程", ("物理远程", "法术远程")),
        ("失控的骑士", "近战", ("物理近战",)),
        ("损坏的战车", "近战", ("物理近战",)),
    )
    opening_add_checks = []
    for attempt in attempts:
        attempt_start_sec = seconds(attempt["start"])
        attempt_end_sec = seconds(attempt["end"])
        for target, responsibility, eligible_roles in opening_add_specs:
            death_row = next((
                row for row in king_rows
                if attempt_start_sec <= row["sec"] <= attempt_end_sec
                and row["body"] == target + "死亡了。"
            ), None)
            deadline_sec = death_row["sec"] if death_row else attempt_end_sec
            deadline_reason = "小怪死亡"
            if (
                attempt["attempt"] == 1
                and target == "干枯的主教"
                and bishop_fear_sec is not None
                and bishop_fear_sec < deadline_sec
            ):
                deadline_sec = bishop_fear_sec
                deadline_reason = "恐惧结算"
            eligible = sorted(
                player for player, role in role_by_name.items()
                if role in eligible_roles
            )
            window_end_offset = deadline_sec - attempt_start_sec
            counts_errors = (
                deadline_reason == "恐惧结算"
                or window_end_offset > 10.0
            )
            contribution = defaultdict(lambda: {"hits": 0, "damage": 0})
            for event in parsed_damage:
                if (
                    attempt_start_sec <= event["sec"] <= deadline_sec
                    and event["target"] == target
                    and event["source"] in eligible
                ):
                    contribution[event["source"]]["hits"] += 1
                    contribution[event["source"]]["damage"] += event["damage"]
            results = [{
                "player": player,
                "hits": contribution[player]["hits"],
                "damage": contribution[player]["damage"],
                "is_error": (
                    counts_errors and contribution[player]["hits"] == 0
                ),
            } for player in eligible]
            opening_add_checks.append({
                "attempt": attempt["attempt"],
                "target": target,
                "responsibility": responsibility,
                "eligible_roles": list(eligible_roles),
                "window_end_offset": round(window_end_offset, 3),
                "window_end_reason": deadline_reason,
                "counts_errors": counts_errors,
                "result": (
                    "正常检查"
                    if counts_errors else "10秒内击杀，零伤害不计错"
                ),
                "eligible_count": len(eligible),
                "results": results,
                "noncontributors": [
                    item["player"] for item in results if item["is_error"]
                ],
            })

    deaths = []
    for row in king_rows:
        match = re.match(r"(.+?)死亡了。", row["body"])
        if not match:
            continue
        raw_player = match.group(1)
        charm_owner = re.match(r"(.+?) \(皇后\)$", raw_player)
        player = charm_owner.group(1) if charm_owner else normalize_unit(raw_player)
        if player not in roster:
            continue
        attempt = next((
            item for item in attempts
            if seconds(item["start"]) <= row["sec"] <= seconds(item["end"])
        ), None)
        if attempt:
            deaths.append({
                "player": player,
                "sec": row["sec"],
                "ts": row["ts"],
                "attempt": attempt["attempt"],
            })

    fury_hits = []
    black_water_hits = []
    for row in king_rows:
        fury = re.match(r"国王的国王之怒击中(.+?)造成(\d+)点", row["body"])
        if fury:
            target = normalize_unit(fury.group(1))
            if target in roster:
                fury_hits.append({"target": target, "sec": row["sec"], "damage": int(fury.group(2))})
        water = re.match(r"虚空地区的吞噬击中(.+?)造成(\d+)点", row["body"])
        if water:
            target = normalize_unit(water.group(1))
            if target in roster:
                black_water_hits.append({"target": target, "sec": row["sec"], "damage": int(water.group(2))})

    mechanic_deaths = []
    for death in deaths:
        fury = next((
            hit for hit in reversed(fury_hits)
            if hit["target"] == death["player"] and 0 <= death["sec"] - hit["sec"] <= 0.12
        ), None)
        recent_damage = [
            event for event in parsed_damage
            if event["target"] == death["player"]
            and death["sec"] - 1.0 <= event["sec"] <= death["sec"] + 0.05
        ]
        killing_blow = max(
            recent_damage,
            key=lambda event: (event["sec"], event["line"]),
            default=None,
        )
        water = (
            killing_blow
            if killing_blow
            and killing_blow["source"] == "虚空地区"
            and killing_blow["spell"] == "吞噬"
            else None
        )
        if fury:
            mechanic_deaths.append({
                "attempt": death["attempt"],
                "player": death["player"],
                "mechanic": "国王之怒",
                "ts": death["ts"],
                "damage": fury["damage"],
            })
        elif water:
            mechanic_deaths.append({
                "attempt": death["attempt"],
                "player": death["player"],
                "mechanic": "黑水（罪孽深重生成的虚空地区·吞噬）",
                "ts": death["ts"],
                "damage": water["damage"],
            })

    late_bows = []
    for row in king_rows:
        match = re.match(r"皇后的黑暗屈从使(.+?)受到了(\d+)点暗影伤害", row["body"])
        if not match:
            continue
        player = normalize_unit(match.group(1))
        attempt = next((
            item for item in attempts
            if seconds(item["start"]) <= row["sec"] <= seconds(item["end"])
        ), None)
        if attempt and player in roster:
            applied = next((
                candidate for candidate in reversed(king_rows)
                if candidate["sec"] <= row["sec"]
                and candidate["body"] == player + "受到了黑暗屈从效果的影响（1）。"
            ), None)
            late_bows.append({
                "attempt": attempt["attempt"],
                "player": player,
                "applied_offset": round(applied["sec"] - seconds(attempt["start"]), 3) if applied else None,
                "damage_offset": round(row["sec"] - seconds(attempt["start"]), 3),
                "delay": round(row["sec"] - applied["sec"], 3) if applied else None,
                "damage": int(match.group(2)),
                "died": any(
                    death["player"] == player and 0 <= death["sec"] - row["sec"] <= 0.12
                    for death in deaths
                ),
            })

    second_death_sequence = []

    charm_events = []
    for row in king_rows:
        gain = re.match(r"(.+?) \(皇后\)受到了魅惑之心效果的影响（1）。", row["body"])
        if gain:
            player = normalize_unit(gain.group(1))
            if player in roster:
                charm_events.append({"player": player, "sec": row["sec"], "ts": row["ts"]})
    first_charm_issues = []
    seen_charmed = set()
    for gain in charm_events:
        if gain["player"] in seen_charmed:
            continue
        seen_charmed.add(gain["player"])
        fade = next((
            row for row in king_rows
            if row["sec"] >= gain["sec"]
            and row["body"] == "魅惑之心效果从%s身上消失。" % gain["player"]
        ), None)
        death = next((
            item for item in deaths
            if item["player"] == gain["player"] and item["sec"] >= gain["sec"]
        ), None)
        resolution_sec = min(
            [item["sec"] for item in (fade, death) if item is not None],
            default=None,
        )
        duration = round(resolution_sec - gain["sec"], 3) if resolution_sec is not None else None
        if fade is None or duration is None or duration > 3.0:
            attempt = next(
                item for item in attempts
                if seconds(item["start"]) <= gain["sec"] <= seconds(item["end"])
            )
            first_charm_issues.append({
                "attempt": attempt["attempt"],
                "player": gain["player"],
                "offset": round(gain["sec"] - seconds(attempt["start"]), 3),
                "duration": duration,
                "resolution": "死亡前未解除" if death and (fade is None or death["sec"] <= fade["sec"]) else "超过3秒后解除",
            })

    decurse_counts = Counter()
    decurse_targets = defaultdict(Counter)
    for row in combat_rows:
        cast = re.match(r"(.+?)对(.+?)施放了(解除诅咒|解除次级诅咒)", row["body"])
        if not cast:
            self_cast = re.match(r"你施放了解除诅咒", row["body"])
            if self_cast:
                decurse_counts[LOGGER_NAME] += 1
                decurse_targets[LOGGER_NAME][LOGGER_NAME] += 1
            continue
        caster = normalize_unit(cast.group(1))
        target = normalize_unit(cast.group(2))
        if caster in roster:
            decurse_counts[caster] += 1
            decurse_targets[caster][target] += 1

    wipe_summaries = []

    return {
        "attempts": attempts,
        "black_water_name": "罪孽深重生成的虚空地区；实际伤害技能为吞噬",
        "first_attempt_bishop_fear": first_attempt_bishop_fear,
        "opening_add_checks": opening_add_checks,
        "mechanic_deaths": mechanic_deaths,
        "late_bows": late_bows,
        "second_attempt_death_sequence": second_death_sequence,
        "first_charm_rule": "每名玩家三次尝试中的首次魅惑之心；3秒内解除视为及时自解，超过3秒或死亡前未解除列出。普通日志不记录解除手段，因此这是按持续时间判定。",
        "first_charm_issues": first_charm_issues,
        "decurse_counts": [{
            "player": player,
            "class": PLAYER_CLASSES.get(player, "未知"),
            "count": decurse_counts[player],
            "targets": [
                {"target": target, "count": count}
                for target, count in decurse_targets[player].most_common()
            ],
        } for player in sorted(
            (
                name for name in roster
                if PLAYER_CLASSES.get(name) in ("法师", "德鲁伊")
            ),
            key=lambda name: (-decurse_counts[name], name),
        )],
        "wipe_summaries": wipe_summaries,
    }


ARCANE_RESIST_BASE_ITEMS = {
    55518: 30, 55519: 20, 55520: 30, 55521: 30,
    55522: 30, 55523: 20, 55524: 30, 55525: 30,
    55526: 30, 55527: 20, 55528: 30, 55529: 30,
    55530: 30, 55531: 20, 55532: 30, 55533: 30,
    55534: 20,
}
ARCANE_RESIST_BASE_NAMES = {
    "Cosmic Headdress": 30, "宇宙头饰": 30,
    "Cosmic Mantle": 20, "宇宙衬肩": 20,
    "Cosmic Vest": 30, "宇宙外衣": 30,
    "Cosmic Leggings": 30, "宇宙护腿": 30,
    "Ethereal Helmet": 30, "虚灵头饰": 30,
    "Ethereal Shoulder Pads": 20, "虚灵护肩": 20,
    "Ethereal Tunic": 30, "虚灵外套": 30,
    "Ethereal Leggings": 30, "虚灵护腿": 30,
    "Otherworldly Coif": 30, "超凡罩帽": 30,
    "Otherworldly Spaulders": 20, "超凡肩甲": 20,
    "Otherworldly Breastplate": 30, "超凡胸甲": 30,
    "Otherworldly Leggings": 30, "超凡护腿": 30,
    "Reflective Helmet": 30, "炫光头盔": 30,
    "Reflective Pauldrons": 20, "炫光肩铠": 20,
    "Reflective Breastplate": 30, "炫光胸甲": 30,
    "Reflective Leggings": 30, "炫光护腿": 30,
    "Ley-Kissed Drape": 20, "魔网亲和披风": 20,
}
ARCANE_RESIST_ENCHANTS = {1250: 8, 1257: 15, 1267: 25, 2485: 5}


def union_length(intervals):
    total = 0
    cursor = None
    for left, right in sorted(intervals):
        if cursor is None or left > cursor:
            total += max(0, right - left)
            cursor = right
        elif right > cursor:
            total += right - cursor
            cursor = right
    return total


def mark_chained_overloads(overloads, window=1.0):
    roots = sorted(
        (item for item in overloads if item["trigger"] != "持有者死亡"),
        key=lambda item: item["resolved_offset"],
    )
    for item in overloads:
        if item["trigger"] != "持有者死亡":
            continue
        root = next((
            other for other in roots
            if abs(item["resolved_offset"] - other["resolved_offset"]) <= window
        ), None)
        if root is None:
            continue
        item["chained_to"] = root["player"]
        item["counted_error"] = False


def anomalus_gear_snapshots(roster):
    pull_epoch_ms = epoch_ms_at(encounter_window("阿诺玛鲁斯")[0])
    snapshots = {}
    aura_snapshots = {}
    for path in [CUSTOM_DATA_PATH] if CUSTOM_DATA_PATH else CUSTOM_DATA_FILES:
        _read_gear_snapshots(path, roster, pull_epoch_ms, snapshots, aura_snapshots)
    for player, snapshot in snapshots.items():
        snapshot["auras"] = aura_snapshots.get(player, {}).get("auras", set())
    return snapshots


def _read_gear_snapshots(path, roster, pull_epoch_ms, snapshots, aura_snapshots):
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if "|UNIT_INFO|" in line:
                fields = line.rstrip().split("|")
                if len(fields) >= 8:
                    timestamp = int(fields[0])
                    player = fields[4]
                    if player in roster and timestamp <= pull_epoch_ms:
                        previous = aura_snapshots.get(player)
                        if previous is None or timestamp >= previous["timestamp"]:
                            aura_snapshots[player] = {
                                "timestamp": timestamp,
                                "auras": {
                                    int(entry.split("=", 1)[0])
                                    for entry in fields[7].split(",")
                                    if "=" in entry
                                },
                            }
                continue
            if "|COMBATANT_INFO|" not in line:
                continue
            fields = line.rstrip().split("|")
            if len(fields) < 11:
                continue
            timestamp = int(fields[0])
            player = fields[3]
            if player not in roster or timestamp > pull_epoch_ms:
                continue
            previous = snapshots.get(player)
            if previous is None or timestamp >= previous["timestamp"]:
                snapshots[player] = {
                    "timestamp": timestamp,
                    "race": fields[5],
                    "equipment": fields[10],
                }


def arcane_resist_from_equipment(equipment):
    total = 0
    components = []
    unresolved = []
    for slot in equipment.split("&"):
        if ";" not in slot:
            continue
        item_name, item_code = slot.rsplit(";", 1)
        values = item_code.split(":")
        try:
            item_id = int(values[0])
            enchant_id = int(values[1])
            suffix_id = int(values[2])
        except (ValueError, IndexError):
            continue
        if item_id in ARCANE_RESIST_ITEMS:
            base_value = ARCANE_RESIST_ITEMS[item_id]
        elif normalize_item_name(item_name) in ARCANE_RESIST_NAMES:
            base_value = ARCANE_RESIST_NAMES[normalize_item_name(item_name)]
        else:
            base_value = 0
            unresolved.append(item_name)
        if base_value:
            total += base_value
            components.append("%s +%d" % (item_name, base_value))
        enchant_value = ARCANE_RESIST_ENCHANTS.get(enchant_id, 0)
        if enchant_value:
            total += enchant_value
            components.append("%s附魔 +%d" % (item_name, enchant_value))
        if "奥术抗性" in item_name and 1307 <= suffix_id <= 1352:
            suffix_value = suffix_id - 1306
            total += suffix_value
            components.append("%s词缀 +%d" % (item_name, suffix_value))
    return total, components, unresolved


def analyze_rupturan(rows, roster, parsed_damage, roles):
    start, end = encounter_window("破碎者鲁普图兰")
    start_sec, end_sec = seconds(start), seconds(end)
    row_bodies = {row["line"]: row["body"] for row in rows}

    fragment_first = min(
        (
            event["sec"] for event in parsed_damage
            if start_sec <= event["sec"] <= end_sec
            and event["target"] == "鲁普图兰的碎块"
        ),
        default=end_sec,
    )

    player_deaths = []
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec + 10):
            continue
        death = re.match(r"(.+?)死亡了。", row["body"])
        if death and normalize_unit(death.group(1)) in roster:
            player_deaths.append({
                "player": normalize_unit(death.group(1)),
                "sec": row["sec"],
                "ts": row["ts"],
            })

    eruption_hits = []
    for event in parsed_damage:
        if (
            start_sec <= event["sec"] < fragment_first
            and event["source"] == "摇摇欲坠的流放者"
            and event["spell"] == "喷发"
            and event["target"] in roster
        ):
            eruption_hits.append(event)
    eruption_deaths = []
    for death in player_deaths:
        hit = next((
            event for event in eruption_hits
            if event["target"] == death["player"]
            and abs(event["sec"] - death["sec"]) <= 0.2
        ), None)
        if hit:
            eruption_deaths.append({
                "player": death["player"],
                "offset": round(death["sec"] - start_sec, 3),
                "damage": hit["damage"],
            })

    boss_damage = sorted(
        (
            event for event in parsed_damage
            if start_sec <= event["sec"] <= fragment_first
            and event["source"] in roster
            and event["target"] == "破碎者鲁普图兰"
        ),
        key=lambda event: (event["sec"], event["line"]),
    )
    total_boss_damage = sum(event["damage"] for event in boss_damage)
    threshold_damage = total_boss_damage * 0.95
    cumulative = 0
    five_pct_sec = fragment_first
    for event in boss_damage:
        cumulative += event["damage"]
        if cumulative >= threshold_damage:
            five_pct_sec = event["sec"]
            break

    living_stone_events = [
        event for event in parsed_damage
        if start_sec <= event["sec"] < fragment_first
        and event["target"] == "活体石块"
    ]
    living_stone_deaths = [
        row["sec"] for row in rows
        if start_sec <= row["sec"] < fragment_first
        and row["body"] == "活体石块死亡了。"
    ]
    stone_windows = []
    previous_death = start_sec
    for death_sec in living_stone_deaths:
        mentions = [
            event["sec"] for event in living_stone_events
            if previous_death < event["sec"] <= death_sec
        ]
        if mentions:
            stone_windows.append((min(mentions), death_sec))
        previous_death = death_sec

    def is_active_player_attack(event, target):
        body = row_bodies.get(event["line"], "")
        return (
            event["source"] in roster
            and event["target"] == target
            and event["spell"] != "宠物近战"
            and not event["spell"].startswith("宠物：")
            and ("效果使%s" % target) not in body
            and ("使%s受到了" % target) not in body
        )

    low_health_attacks = defaultdict(lambda: {"hits": 0, "damage": 0, "spells": Counter()})
    for event in boss_damage:
        if event["sec"] < five_pct_sec or not is_active_player_attack(event, "破碎者鲁普图兰"):
            continue
        if not any(left <= event["sec"] <= right for left, right in stone_windows):
            continue
        item = low_health_attacks[event["source"]]
        item["hits"] += 1
        item["damage"] += event["damage"]
        item["spells"][event["spell"]] += 1
    low_health_boss_issues = [{
        "player": player,
        "hits": values["hits"],
        "damage": values["damage"],
        "spells": values["spells"].most_common(5),
    } for player, values in sorted(
        low_health_attacks.items(), key=lambda item: (-item[1]["damage"], item[0])
    )]

    remote_players = sorted(
        item["name"] for item in roles
        if item["role"] in ("物理远程", "法术远程")
        and item["class"] not in ("术士", "牧师")
    )
    living_fragment_deaths = [
        row["sec"] for row in rows
        if fragment_first <= row["sec"] <= end_sec
        and row["body"] == "活体碎块死亡了。"
    ]
    living_fragment_kills = []
    for death in player_deaths:
        killing_event = next((
            event for event in parsed_damage
            if event["source"] == "活体碎块"
            and event["target"] == death["player"]
            and abs(event["sec"] - death["sec"]) <= 0.2
        ), None)
        if not killing_event:
            continue
        previous_add_death = max(
            [sec for sec in living_fragment_deaths if sec < death["sec"]]
            or [fragment_first]
        )
        window_start = max(previous_add_death, death["sec"] - 10.0)
        damage_by_remote = Counter()
        hits_by_remote = Counter()
        for event in parsed_damage:
            if not (window_start <= event["sec"] <= death["sec"]):
                continue
            if event["target"] != "活体碎块" or event["source"] not in remote_players:
                continue
            damage_by_remote[event["source"]] += event["damage"]
            hits_by_remote[event["source"]] += 1
        living_fragment_kills.append({
            "victim": death["player"],
            "offset": round(death["sec"] - start_sec, 3),
            "spell": killing_event["spell"],
            "damage": killing_event["damage"],
            "window": round(death["sec"] - window_start, 3),
            "non_attackers": [
                player for player in remote_players if hits_by_remote[player] == 0
            ],
            "attackers": [{
                "player": player,
                "hits": hits_by_remote[player],
                "damage": damage_by_remote[player],
            } for player in remote_players if hits_by_remote[player] > 0],
        })

    mana_responsible = sorted(
        item["name"] for item in roles
        if item["class"] == "术士"
        or (item["class"] == "牧师" and item["role"] == "法术远程")
    )
    mana_drains = defaultdict(lambda: {"ticks": 0, "amount": 0, "spells": Counter()})
    for row in rows:
        if not (fragment_first <= row["sec"] <= end_sec):
            continue
        drain = re.match(
            r"(.+?)的吸取法力从恶魔之心身上吸取了(\d+)点法力值",
            row["body"],
        )
        if drain:
            player = normalize_unit(drain.group(1))
            if player in mana_responsible:
                amount = int(drain.group(2))
                mana_drains[player]["ticks"] += 1
                mana_drains[player]["amount"] += amount
                mana_drains[player]["spells"]["吸取法力"] += 1
    for event in parsed_damage:
        if (
            fragment_first <= event["sec"] <= end_sec
            and event["target"] == "恶魔之心"
            and event["source"] in mana_responsible
            and event["spell"] == "法力燃烧"
        ):
            mana_drains[event["source"]]["ticks"] += 1
            mana_drains[event["source"]]["amount"] += event["damage"]
            mana_drains[event["source"]]["spells"]["法力燃烧"] += 1

    energy_bursts = []
    for event in parsed_damage:
        if (
            fragment_first <= event["sec"] <= end_sec + 5
            and event["source"] == "恶魔之心"
            and event["spell"] == "能量爆发"
            and event["target"] in roster
        ):
            energy_bursts.append(event)

    return {
        "start": start,
        "end": end,
        "phase_two_offset": round(fragment_first - start_sec, 3),
        "eruption_deaths": eruption_deaths,
        "five_pct_method": "以一阶段本体可见总承伤的95%累计点倒推5%血量阈值",
        "five_pct_offset": round(five_pct_sec - start_sec, 3),
        "living_stone_windows": [{
            "first_offset": round(left - start_sec, 3),
            "death_offset": round(right - start_sec, 3),
        } for left, right in stone_windows],
        "living_fragment_responsibility": "物理远程与法术远程，但排除负责对恶魔之心抽蓝的术士和牧师",
        "low_health_boss_issues": low_health_boss_issues,
        "living_fragment_kills": living_fragment_kills,
        "mana_drains": [{
            "player": player,
            "class": next(item["class"] for item in roles if item["name"] == player),
            "ticks": mana_drains[player]["ticks"],
            "amount": mana_drains[player]["amount"],
            "spells": mana_drains[player]["spells"].most_common(),
        } for player in mana_responsible],
        "mana_noncontributors": [
            player for player in mana_responsible if mana_drains[player]["ticks"] == 0
        ],
        "energy_burst": {
            "occurred": bool(energy_bursts),
            "hits": len(set(event["target"] for event in energy_bursts)),
            "damage": sum(event["damage"] for event in energy_bursts),
        },
    }


def analyze_kruul(rows, roster, parsed_damage, roles, dispel_candidates):
    start, end = encounter_window("库鲁尔")
    start_sec, end_sec = seconds(start), seconds(end)

    boss_taunts = []
    role_tanks = {
        item["name"] for item in roles if item["role"] == "坦克"
    }
    observed_tanks = set(role_tanks)
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        taunt = re.match(
            r"(.+?)对(库鲁尔|虛空地狱火)使用(嘲讽|低吼|清算之手)",
            row["body"],
        )
        if not taunt:
            continue
        caster = normalize_unit(taunt.group(1))
        observed_tanks.add(caster)
        if taunt.group(2) == "库鲁尔":
            boss_taunts.append({
                "player": caster,
                "spell": taunt.group(3),
                "sec": row["sec"],
                "offset": round(row["sec"] - start_sec, 3),
            })
    cold_applications = Counter()
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        stack = re.match(r"(.+?)受到了冷漠打击效果的影响（(\d+)）", row["body"])
        if stack:
            player = normalize_unit(stack.group(1))
            if player in role_tanks:
                cold_applications[player] += 1
    encounter_tanks = [
        player for player, count in sorted(
            cold_applications.items(),
            key=lambda item: (-item[1], item[0]),
        )[:4]
    ]

    def cold_tank_state_at(cutoff_line):
        state = {}
        for row in rows:
            if row["line"] > cutoff_line:
                break
            if not (start_sec <= row["sec"] <= end_sec):
                continue
            stack = re.match(r"(.+?)受到了冷漠打击效果的影响（(\d+)）", row["body"])
            if stack:
                player = normalize_unit(stack.group(1))
                if player in encounter_tanks:
                    state[player] = int(stack.group(2))
            loss = re.match(r"冷漠打击效果从(.+?)身上消失", row["body"])
            if loss:
                state.pop(normalize_unit(loss.group(1)), None)
        return state

    high_stack_events = []
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        stack = re.match(r"(.+?)受到了冷漠打击效果的影响（(\d+)）", row["body"])
        if not stack or int(stack.group(2)) < 7:
            continue
        player = normalize_unit(stack.group(1))
        if player not in roster:
            continue
        high_stack_events.append({
            "player": player,
            "stack": int(stack.group(2)),
            "sec": row["sec"],
            "line": row["line"],
        })

    high_stack_incidents = []
    for event in high_stack_events:
        intervening_taunt = bool(
            high_stack_incidents
            and any(
                high_stack_incidents[-1]["sec"] < item["sec"] <= event["sec"]
                for item in boss_taunts
            )
        )
        active_tanks = None
        if high_stack_incidents and intervening_taunt:
            tank_state = cold_tank_state_at(event["line"])
            active_tanks = [
                player for player, stack in sorted(
                    tank_state.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:2]
            ]
            if sorted(active_tanks) == sorted(high_stack_incidents[-1]["active_tanks"]):
                intervening_taunt = False
        if not high_stack_incidents or intervening_taunt:
            holding_taunt = next((
                item for item in reversed(boss_taunts)
                if item["sec"] <= event["sec"]
            ), None)
            late_taunt = next((
                item for item in boss_taunts
                if item["sec"] > event["sec"]
            ), None)
            if active_tanks is None:
                tank_state = cold_tank_state_at(event["line"])
                active_tanks = [
                    player for player, stack in sorted(
                        tank_state.items(),
                        key=lambda item: (-item[1], item[0]),
                    )[:2]
                ]
            responsible_tanks = [
                player for player in encounter_tanks
                if player not in active_tanks
            ]
            high_stack_incidents.append({
                "sec": event["sec"],
                "offset": round(event["sec"] - start_sec, 3),
                "stack": event["stack"],
                "players": [event["player"]],
                "active_tanks": active_tanks,
                "responsible_tanks": responsible_tanks,
                "holding_taunter": holding_taunt["player"] if holding_taunt else None,
                "holding_taunt_spell": holding_taunt["spell"] if holding_taunt else None,
                "holding_taunt_offset": holding_taunt["offset"] if holding_taunt else None,
                "missed_taunter": late_taunt["player"] if late_taunt else "未记录后续接嘲讽T",
                "late_taunt_spell": late_taunt["spell"] if late_taunt else None,
                "late_taunt_offset": late_taunt["offset"] if late_taunt else None,
                "late_by": (
                    round(late_taunt["sec"] - event["sec"], 3)
                    if late_taunt else None
                ),
            })
        else:
            if event["player"] not in high_stack_incidents[-1]["players"]:
                high_stack_incidents[-1]["players"].append(event["player"])
            high_stack_incidents[-1]["stack"] = max(
                high_stack_incidents[-1]["stack"], event["stack"]
            )

    boss_damage = sorted([
        event for event in parsed_damage
        if start_sec <= event["sec"] <= end_sec
        and event["target"] == "库鲁尔"
    ], key=lambda event: (event["sec"], event["line"]))
    total_boss_damage = sum(event["damage"] for event in boss_damage)
    half_damage = total_boss_damage * 0.5
    cumulative = 0
    half_sec = end_sec
    for event in boss_damage:
        cumulative += event["damage"]
        if cumulative >= half_damage:
            half_sec = event["sec"]
            break

    infernal_damage = defaultdict(lambda: {
        "hits": 0,
        "damage": 0,
        "first_sec": None,
        "spells": Counter(),
    })
    for event in parsed_damage:
        if not (start_sec <= event["sec"] <= half_sec):
            continue
        if event["target"] != "虛空地狱火":
            continue
        if event["source"] not in roster or event["source"] in observed_tanks:
            continue
        item = infernal_damage[event["source"]]
        item["hits"] += 1
        item["damage"] += event["damage"]
        item["spells"][event["spell"]] += 1
        if item["first_sec"] is None:
            item["first_sec"] = event["sec"]
    infernal_issues = [{
        "player": player,
        "first_offset": round(values["first_sec"] - start_sec, 3),
        "hits": values["hits"],
        "damage": values["damage"],
        "spells": values["spells"].most_common(),
    } for player, values in sorted(
        infernal_damage.items(),
        key=lambda item: (-item[1]["damage"], item[0]),
    )]

    mark_explosions = [
        item for item in dispel_candidates
        if item["encounter"] == "库鲁尔" and item["removed"] == "大领主印记"
    ]
    return {
        "start": start,
        "end": end,
        "high_stack_aura": "冷漠打击",
        "encounter_tanks": encounter_tanks,
        "high_stack_incidents": high_stack_incidents,
        "mark_explosions": mark_explosions,
        "phase_one_method": "旧日志无血量，按库鲁尔本体可见总承伤的累计50%点倒推一阶段结束",
        "phase_one_end_offset": round(half_sec - start_sec, 3),
        "observed_tanks": sorted(observed_tanks),
        "infernal_issues": infernal_issues,
    }


def analyze_mephistroth(rows, roster, parsed_damage, roles):
    start, end = encounter_window("孟菲斯托斯")
    start_sec, end_sec = seconds(start), seconds(end)
    row_bodies = {row["line"]: row["body"] for row in rows}
    tanks = {
        item["name"] for item in roles if item["role"] == "坦克"
    }

    mechanics = [
        {
            "name": "外域的末日",
            "kind": "诅咒",
            "rule": "必须及时解除；未解除会直接杀死目标",
        },
        {
            "name": "无眠苦痛",
            "kind": "诅咒",
            "rule": "噩梦爬行者施加，可解除",
        },
        {
            "name": "军团镣铐",
            "kind": "控制效果（不是诅咒）",
            "rule": "等待自然消失；异常提前挣脱会由触发者施放“挣脱镣铐”炸团",
        },
        {
            "name": "梦魇乍醒",
            "kind": "点名效果",
            "rule": "约3秒后生成噩梦爬行者；日志仅见自然消失，不按可驱散诅咒处理",
        },
        {
            "name": "吸血鬼光环",
            "kind": "Boss增益",
            "rule": "应对Boss驱散",
        },
        {
            "name": "地狱之怒碎片 / 深渊之恨",
            "kind": "水晶阶段",
            "rule": "击杀6个地狱之怒碎片；未处理会使深渊之恨周期性对全团造成约3000火焰伤害",
        },
    ]

    curse_dispels = []
    doom_applications = []
    active_doom = {}
    doom_deaths = []
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        applied = re.match(r"(.+?)受到了外域的末日效果的影响", row["body"])
        if applied:
            target = normalize_unit(applied.group(1))
            if target in roster:
                episode = {
                    "target": target,
                    "applied_sec": row["sec"],
                    "applied_offset": round(row["sec"] - start_sec, 3),
                }
                doom_applications.append(episode)
                active_doom[target] = episode
            continue
        removed = re.match(r"(.+?)的(外域的末日|无眠苦痛)被移除了", row["body"])
        if removed:
            target = normalize_unit(removed.group(1))
            aura = removed.group(2)
            dispeller = None
            dispel_spell = None
            for candidate in rows:
                if abs(candidate["sec"] - row["sec"]) > 0.25:
                    continue
                cast = re.match(
                    r"(.+?)对" + re.escape(target)
                    + r"施放了(解除诅咒|解除次级诅咒)",
                    candidate["body"],
                )
                if cast:
                    dispeller = normalize_unit(cast.group(1))
                    dispel_spell = cast.group(2)
                    break
            curse_dispels.append({
                "aura": aura,
                "target": target,
                "dispeller": dispeller or "未识别",
                "spell": dispel_spell or "未识别",
                "offset": round(row["sec"] - start_sec, 3),
            })
            if aura == "外域的末日" and target in active_doom:
                active_doom[target]["resolved_sec"] = row["sec"]
                active_doom[target]["resolution"] = "已解除"
                active_doom.pop(target, None)
            continue
        killed = re.match(r"(.+?)被外域的末日杀死了", row["body"])
        if killed:
            target = normalize_unit(killed.group(1))
            doom_deaths.append({
                "target": target,
                "offset": round(row["sec"] - start_sec, 3),
            })
            if target in active_doom:
                active_doom[target]["resolved_sec"] = row["sec"]
                active_doom[target]["resolution"] = "未解除并死亡"
                active_doom.pop(target, None)

    for episode in doom_applications:
        resolved_sec = episode.get("resolved_sec", end_sec)
        episode["duration"] = round(resolved_sec - episode["applied_sec"], 3)
        episode.setdefault("resolution", "战斗结束前未见结算")

    shackle_damage = defaultdict(lambda: {
        "targets": set(),
        "hits": 0,
        "damage": 0,
        "first_sec": None,
    })
    for event in parsed_damage:
        if (
            start_sec <= event["sec"] <= end_sec
            and event["spell"] == "挣脱镣铐"
            and event["source"] in roster
            and event["target"] in roster
        ):
            item = shackle_damage[event["source"]]
            item["targets"].add(event["target"])
            item["hits"] += 1
            item["damage"] += event["damage"]
            if item["first_sec"] is None:
                item["first_sec"] = event["sec"]
    shackle_explosions = [{
        "trigger": player,
        "offset": round(values["first_sec"] - start_sec, 3),
        "hits": len(values["targets"]),
        "damage": values["damage"],
    } for player, values in sorted(shackle_damage.items())]

    boss_damage = sorted([
        event for event in parsed_damage
        if start_sec <= event["sec"] <= end_sec
        and event["target"] == "孟菲斯托斯"
    ], key=lambda event: (event["sec"], event["line"]))
    total_boss_damage = sum(event["damage"] for event in boss_damage)

    def boss_remaining_threshold_sec(remaining_fraction):
        threshold_damage = total_boss_damage * (1.0 - remaining_fraction)
        cumulative = 0
        for event in boss_damage:
            cumulative += event["damage"]
            if cumulative >= threshold_damage:
                return event["sec"]
        return end_sec

    thirty_sec = boss_remaining_threshold_sec(0.30)

    eye_applications = []
    eye_removals = []
    eye_dispels = []
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        applied = re.match(
            r"(.+?)受到了沉睡麻痹效果的影响", row["body"]
        )
        if applied:
            eye_applications.append({
                "player": normalize_unit(applied.group(1)),
                "sec": row["sec"],
            })
        removed = re.match(
            r"(.+?)的沉睡麻痹被移除了", row["body"]
        )
        if removed:
            eye_removals.append({
                "player": normalize_unit(removed.group(1)),
                "sec": row["sec"],
            })
        dispel = re.match(
            r"(.+?)对(.+?)施放了(清洁术|净化术|净化|驱散魔法|消毒术)",
            row["body"],
        )
        if dispel:
            eye_dispels.append({
                "caster": normalize_unit(dispel.group(1)),
                "target": normalize_unit(dispel.group(2)),
                "spell": dispel.group(3),
                "sec": row["sec"],
            })
    eye_bait_counts = Counter(
        item["player"] for item in eye_applications
    )
    eye_dispeller_counts = Counter()
    eye_episodes = []
    for index, application in enumerate(eye_applications):
        next_application_sec = (
            eye_applications[index + 1]["sec"]
            if index + 1 < len(eye_applications) else end_sec
        )
        removal = next((
            item for item in eye_removals
            if item["player"] == application["player"]
            and application["sec"] <= item["sec"] < next_application_sec
        ), None)
        dispel = next((
            item for item in eye_dispels
            if removal is not None
            and item["target"] == application["player"]
            and removal["sec"] <= item["sec"] <= removal["sec"] + 0.25
        ), None)
        if dispel:
            eye_dispeller_counts[dispel["caster"]] += 1
        eye_episodes.append({
            "target": application["player"],
            "applied_offset": round(application["sec"] - start_sec, 3),
            "removed_offset": (
                round(removal["sec"] - start_sec, 3) if removal else None
            ),
            "dispeller": dispel["caster"] if dispel else None,
            "dispel_spell": dispel["spell"] if dispel else None,
        })
    eye_bait = (
        eye_bait_counts.most_common(1)[0][0] if eye_bait_counts else None
    )
    eye_dispeller = (
        eye_dispeller_counts.most_common(1)[0][0]
        if eye_dispeller_counts else None
    )
    crawler_exempt_players = {
        player for player in (eye_bait, eye_dispeller) if player
    }

    crawler_spawns = []
    crawler_deaths = []
    crawler_mana_drain_starts = []
    crawler_mana_drain_hits = []
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        if row["body"] == "孟菲斯托斯施放了梦魇乍醒。":
            crawler_spawns.append(row["sec"])
        elif row["body"] == "噩梦爬行者死亡了。":
            crawler_deaths.append(row["sec"])
        elif row["body"] == "噩梦爬行者获得了无尽饥渴的效果（1）。":
            crawler_mana_drain_starts.append(row["sec"])
        elif re.match(r"噩梦爬行者的无尽饥渴击中.+造成\d+点伤害。", row["body"]):
            crawler_mana_drain_hits.append(row["sec"])
    ranged = sorted(
        item["name"] for item in roles
        if item["role"] in ("物理远程", "法术远程")
    )
    crawler_waves = []
    for index, spawn_sec in enumerate(crawler_spawns):
        death_sec = crawler_deaths[index] if index < len(crawler_deaths) else end_sec
        duration = death_sec - spawn_sec
        next_spawn_sec = (
            crawler_spawns[index + 1]
            if index + 1 < len(crawler_spawns)
            else end_sec + 1
        )
        drain_starts = [
            moment for moment in crawler_mana_drain_starts
            if spawn_sec <= moment <= death_sec and moment < next_spawn_sec
        ]
        drain_hits = [
            moment for moment in crawler_mana_drain_hits
            if spawn_sec <= moment <= death_sec and moment < next_spawn_sec
        ]
        first_drain_start = drain_starts[0] if drain_starts else None
        first_drain_hit = next((
            moment for moment in drain_hits
            if first_drain_start is not None and moment >= first_drain_start
        ), None)
        mana_drain_success = first_drain_hit is not None
        mana_drain_counts_as_error = (
            mana_drain_success and first_drain_hit < thirty_sec
        )
        contribution_end_sec = first_drain_hit if mana_drain_success else death_sec
        contribution = defaultdict(lambda: {"hits": 0, "damage": 0})
        for event in parsed_damage:
            if (
                spawn_sec <= event["sec"] <= contribution_end_sec
                and event["target"] == "噩梦爬行者"
                and event["source"] in ranged
            ):
                contribution[event["source"]]["hits"] += 1
                contribution[event["source"]]["damage"] += event["damage"]
        crawler_waves.append({
            "wave": index + 1,
            "spawn_offset": round(spawn_sec - start_sec, 3),
            "death_offset": round(death_sec - start_sec, 3),
            "duration": round(duration, 3),
            "mana_drain_started": first_drain_start is not None,
            "mana_drain_success": mana_drain_success,
            "mana_drain_counts_as_error": mana_drain_counts_as_error,
            "ignored_below_thirty": (
                mana_drain_success and not mana_drain_counts_as_error
            ),
            "mana_drain_start_offset": (
                round(first_drain_start - start_sec, 3)
                if first_drain_start is not None else None
            ),
            "mana_drain_hit_offset": (
                round(first_drain_hit - start_sec, 3)
                if first_drain_hit is not None else None
            ),
            "ranged_noncontributors": [
                player for player in ranged
                if player not in crawler_exempt_players
                and contribution[player]["hits"] == 0
            ] if mana_drain_counts_as_error else [],
            "eye_duty_exempt_players": sorted(
                player for player in crawler_exempt_players
                if player in ranged
            ),
            "ranged_contributors": [{
                "player": player,
                "hits": contribution[player]["hits"],
                "damage": contribution[player]["damage"],
            } for player in ranged if contribution[player]["hits"] > 0],
        })

    fifty_five_sec = boss_remaining_threshold_sec(0.55)
    crystal_casts = [
        row["sec"] for row in rows
        if start_sec <= row["sec"] <= end_sec
        and row["body"] == "孟菲斯托斯开始施放地狱之怒碎片。"
    ]
    next_crystal_sec = next((
        moment for moment in crystal_casts if moment > fifty_five_sec
    ), end_sec)

    def is_active_boss_damage(event):
        body = row_bodies.get(event["line"], "")
        return (
            event["source"] in roster
            and event["target"] == "孟菲斯托斯"
            and event["spell"] != "宠物近战"
            and not event["spell"].startswith("宠物：")
            and "效果使孟菲斯托斯" not in body
            and "使孟菲斯托斯受到了" not in body
        )

    forbidden_window_damage = defaultdict(lambda: {
        "hits": 0,
        "damage": 0,
        "first_sec": None,
        "spells": Counter(),
    })
    for event in boss_damage:
        if not (fifty_five_sec < event["sec"] < next_crystal_sec):
            continue
        if not is_active_boss_damage(event):
            continue
        if event["source"] in tanks:
            continue
        item = forbidden_window_damage[event["source"]]
        item["hits"] += 1
        item["damage"] += event["damage"]
        item["spells"][event["spell"]] += 1
        if item["first_sec"] is None:
            item["first_sec"] = event["sec"]
    forbidden_boss_attacks = [{
        "player": player,
        "first_offset": round(values["first_sec"] - start_sec, 3),
        "hits": values["hits"],
        "damage": values["damage"],
        "spells": values["spells"].most_common(),
    } for player, values in sorted(
        forbidden_window_damage.items(),
        key=lambda item: (-item[1]["damage"], item[0]),
    )]

    crystal_deaths = [
        row["sec"] for row in rows
        if start_sec <= row["sec"] <= end_sec
        and row["body"] == "地狱之怒碎片死亡了。"
    ]
    deep_hatred_hits = [
        event for event in parsed_damage
        if start_sec <= event["sec"] <= end_sec
        and event["source"] == "孟菲斯托斯"
        and event["spell"] == "深渊之恨"
        and event["target"] in roster
    ]
    crystal_waves = []
    for index, cast_sec in enumerate(crystal_casts):
        wave_end = crystal_casts[index + 1] if index + 1 < len(crystal_casts) else end_sec + 0.01
        deaths = [moment for moment in crystal_deaths if cast_sec <= moment < wave_end]
        hatred = [event for event in deep_hatred_hits if cast_sec <= event["sec"] < wave_end]
        if hatred:
            result = "失败：深渊之恨命中%d人，合计%d伤害" % (
                len(set(event["target"] for event in hatred)),
                sum(event["damage"] for event in hatred),
            )
            issue = True
        elif len(deaths) >= 6:
            result = "成功：6个碎片全部击杀"
            issue = False
        elif index == len(crystal_casts) - 1:
            result = "Boss在深渊之恨结算前死亡，不判错"
            issue = False
        else:
            result = "可见碎片死亡不足6个，需人工复核"
            issue = True
        crystal_waves.append({
            "wave": index + 1,
            "cast_offset": round(cast_sec - start_sec, 3),
            "deaths": len(deaths),
            "last_death_offset": (
                round(max(deaths) - start_sec, 3) if deaths else None
            ),
            "issue": issue,
            "result": result,
        })

    return {
        "start": start,
        "end": end,
        "mechanics": mechanics,
        "curse_dispels": curse_dispels,
        "doom_applications": doom_applications,
        "doom_deaths": doom_deaths,
        "shackle_explosions": shackle_explosions,
        "crawler_failure_rule": "无尽饥渴开始后实际命中玩家",
        "crawler_ignore_below_boss_health_pct": 30,
        "thirty_percent_offset": round(thirty_sec - start_sec, 3),
        "eye_duty": {
            "eye_name": "恶魔之眼",
            "effect": "沉睡麻痹",
            "bait": eye_bait,
            "dispeller": eye_dispeller,
            "exempt_from_crawler": sorted(crawler_exempt_players),
            "bait_counts": dict(sorted(eye_bait_counts.items())),
            "dispeller_counts": dict(sorted(eye_dispeller_counts.items())),
            "episodes": eye_episodes,
        },
        "crawler_waves": crawler_waves,
        "fifty_five_method": "旧日志无血量，按孟菲斯托斯本体可见总承伤累计45%点倒推55%血量",
        "fifty_five_offset": round(fifty_five_sec - start_sec, 3),
        "next_crystal_offset": round(next_crystal_sec - start_sec, 3),
        "forbidden_boss_attacks": forbidden_boss_attacks,
        "crystal_waves": crystal_waves,
        "historical_evidence": {
            "shackle": "历史日志中“挣脱镣铐”的伤害来源直接显示触发者，单次可命中约18–20名团员、每人约4500–7700暗影伤害。",
            "crystal": "历史失败样本中，未处理好水晶会让孟菲斯托斯获得“深渊之恨”，随后约每2秒对全团造成约3000火焰伤害并引发大量死亡。",
        },
    }


def analyze_anomalus(rows, roster, parsed_damage, roles):
    start, end = encounter_window("阿诺玛鲁斯")
    resolution_end = clock_label(seconds(end) + 12.0)
    start_sec, end_sec = seconds(start), seconds(end)
    resolution_end_sec = seconds(resolution_end)
    row_bodies = {row["line"]: row["body"] for row in rows}
    tanks = {
        item["name"] for item in roles if item["role"] == "坦克"
    }

    mark_holders = (
        aura_holders_at(rows, roster, "野性印记", start_sec)
        | aura_holders_at(rows, roster, "野性赐福", start_sec)
    )
    resistance_potion_holders = aura_holders_at(rows, roster, "抗性", start_sec)
    protection_holders = aura_holders_at(rows, roster, "奥术防护", start_sec)
    snapshots = anomalus_gear_snapshots(roster)
    # UNIT_INFO carries the actual aura snapshot and recovers long-lived buffs
    # that were already active when the text combat log began.
    for player, snapshot in snapshots.items():
        if snapshot["auras"] & {9885, 21850}:
            mark_holders.add(player)
        if 11364 in snapshot["auras"]:
            resistance_potion_holders.add(player)
    resistance_rows = []
    for player in sorted(roster):
        snapshot = snapshots.get(player)
        gear_value, components, unresolved = (
            arcane_resist_from_equipment(snapshot["equipment"]) if snapshot else (0, [], [])
        )
        buff_value = 20 if player in mark_holders else 0
        potion_value = 50 if player in resistance_potion_holders else 0
        racial_value = 10 if snapshot and snapshot["race"] == "BloodElf" else 0
        total = gear_value + buff_value + potion_value + racial_value
        detail = list(components)
        if buff_value:
            detail.append("野性印记/赐福 +20")
        if potion_value:
            detail.append("魔法抗性药水（日志效果“抗性”）+50")
        if racial_value:
            detail.append("高等精灵奥术抗性 +10")
        verified = bool(snapshot) and not unresolved
        if verified:
            display_total = str(total)
        elif not snapshot:
            display_total = "无装备快照（已核验下限 %d）" % total
        else:
            display_total = "%d件装备待补（已核验下限 %d）" % (len(unresolved), total)
        if unresolved:
            detail.append("待补装备：" + "、".join(unresolved))
        resistance_rows.append({
            "player": player,
            "total": total,
            "display_total": display_total,
            "gear": gear_value,
            "buff": buff_value,
            "potion": potion_value,
            "racial": racial_value,
            "detail": "；".join(detail) if detail else "日志可核验来源为 0",
            "gear_snapshot": bool(snapshot),
            "verified": verified,
        })
    resistance_rows.sort(key=lambda item: (-item["total"], item["player"]))

    prisons = []
    active_prisons = {}
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec):
            continue
        applied = re.match(r"(.+?)受到了奥术监牢效果的影响", row["body"])
        if applied:
            target = normalize_unit(applied.group(1))
            if target in roster and target not in active_prisons:
                active_prisons[target] = {"target": target, "applied_sec": row["sec"], "ticks": 0}
            continue
        tick = re.match(r"阿诺玛鲁斯的奥术监牢使(.+?)受到了(\d+)点奥术伤害", row["body"])
        if tick:
            target = normalize_unit(tick.group(1))
            if target in active_prisons:
                active_prisons[target]["ticks"] += 1
            continue
        removed = re.match(r"(.+?)的奥术监牢被移除了", row["body"])
        if not removed:
            continue
        target = normalize_unit(removed.group(1))
        prison = active_prisons.pop(target, None)
        if prison is None:
            continue
        dispeller = None
        dispel_spell = None
        for candidate in rows:
            if abs(candidate["sec"] - row["sec"]) > 0.25:
                continue
            cast = re.match(r"(.+?)对" + re.escape(target) + r"施放了(" + "|".join(DISPEL_SPELLS) + r")", candidate["body"])
            if cast:
                dispeller = normalize_unit(cast.group(1))
                dispel_spell = cast.group(2)
                break
        prisons.append({
            "target": target,
            "applied_offset": round(prison["applied_sec"] - start_sec, 3),
            "removed_offset": round(row["sec"] - start_sec, 3),
            "delay": round(row["sec"] - prison["applied_sec"], 3),
            "ticks": prison["ticks"],
            "dispelled": dispeller is not None,
            "dispeller": dispeller,
            "spell": dispel_spell,
        })

    def is_active_boss_damage(event):
        body = row_bodies.get(event["line"], "")
        return (
            event["source"] in roster
            and event["target"] == "阿诺玛鲁斯"
            and event["spell"] != "宠物近战"
            and not event["spell"].startswith("宠物：")
            and "效果使阿诺玛鲁斯" not in body
            and "使阿诺玛鲁斯受到了" not in body
        )

    active_boss_damage = [event for event in parsed_damage if is_active_boss_damage(event)]
    active_boss_actions = list(active_boss_damage)
    for row in rows:
        if not (start_sec <= row["sec"] <= end_sec) or "阿诺玛鲁斯" not in row["body"]:
            continue
        body = row["body"]
        marker = None
        for candidate in ("没有击中阿诺玛鲁斯", "被阿诺玛鲁斯抵抗", "被阿诺玛鲁斯闪躲",
                          "被阿诺玛鲁斯招架", "阿诺玛鲁斯对此免疫", "阿诺玛鲁斯闪躲开了"):
            if candidate in body:
                marker = candidate
                break
        if marker is None:
            continue
        prefix = body.split(marker, 1)[0]
        if "施放失败。" in prefix:
            prefix = prefix.split("施放失败。", 1)[0]
        if "发起了攻击。" in prefix:
            prefix = prefix.split("发起了攻击。", 1)[0]
        source, spell = split_source(prefix.rstrip("。"), roster)
        if source not in roster or spell == "宠物近战" or spell.startswith("宠物："):
            continue
        active_boss_actions.append({
            "source": source, "spell": spell or "未命中攻击",
            "target": "阿诺玛鲁斯", "damage": 0,
            "sec": row["sec"], "line": row["line"],
        })
    active_boss_actions.sort(key=lambda item: (item["sec"], item["line"]))
    explosion_events = [
        event for event in parsed_damage
        if start_sec <= event["sec"] <= resolution_end_sec
        and event["source"] == "阿诺玛鲁斯"
        and event["spell"] == "奥术爆炸"
        and event["target"] in roster
    ]
    explosion_pulses = []
    for event in sorted(explosion_events, key=lambda item: item["sec"]):
        if not explosion_pulses or event["sec"] - explosion_pulses[-1]["last_sec"] > 0.25:
            explosion_pulses.append({
                "sec": event["sec"], "last_sec": event["sec"],
                "targets": set(), "damage": 0,
            })
        pulse = explosion_pulses[-1]
        pulse["last_sec"] = event["sec"]
        pulse["targets"].add(event["target"])
        pulse["damage"] += event["damage"]

    overloads = []
    seen_applications = set()
    active_overloads = {}
    for row in rows:
        if not (start_sec <= row["sec"] <= resolution_end_sec):
            continue
        applied = re.match(r"(.+?)受到了奥术超载效果的影响", row["body"])
        if applied:
            target = normalize_unit(applied.group(1))
            key = (target, row["sec"])
            if target in roster and key not in seen_applications:
                seen_applications.add(key)
                episode = {"target": target, "applied_sec": row["sec"]}
                overloads.append(episode)
                active_overloads[target] = episode
            continue
        removed = re.match(r"奥术超载效果从(.+?)身上消失", row["body"])
        if removed:
            target = normalize_unit(removed.group(1))
            episode = active_overloads.pop(target, None)
            if episode and "removed_sec" not in episode:
                episode["removed_sec"] = row["sec"]

    deaths = []
    for row in rows:
        if start_sec <= row["sec"] <= resolution_end_sec:
            death = re.match(r"(.+?)死亡了", row["body"])
            if death:
                target = normalize_unit(death.group(1))
                if target in roster:
                    deaths.append((target, row["sec"]))

    suppression_gains = {}
    unstable_hits = defaultdict(list)
    for row in rows:
        if not (start_sec <= row["sec"] <= resolution_end_sec):
            continue
        gain = re.match(r"(.+?)受到了奥术抑制效果的影响", row["body"])
        if gain:
            suppression_gains.setdefault(normalize_unit(gain.group(1)), []).append(row["sec"])
    for event in parsed_damage:
        if (
            start_sec <= event["sec"] <= resolution_end_sec
            and event["source"] == "阿诺玛鲁斯"
            and event["spell"] == "不稳定魔法"
            and event["target"] in roster
        ):
            unstable_hits[event["target"]].append(event)

    overload_results = []
    continued_attack_issues = []
    no_soak_issues = []
    for order, episode in enumerate(overloads, 1):
        target = episode["target"]
        applied_sec = episode["applied_sec"]
        removed_sec = episode.get("removed_sec")
        death_sec = next((
            moment for player, moment in deaths
            if player == target
            and applied_sec <= moment
            and (removed_sec is None or moment <= removed_sec + 0.25)
        ), None)
        resolved_sec = death_sec if death_sec is not None else removed_sec
        if resolved_sec is None:
            continue
        pulse = min(
            explosion_pulses,
            key=lambda item: abs(item["last_sec"] - resolved_sec),
        ) if explosion_pulses else None
        if pulse and abs(pulse["last_sec"] - resolved_sec) > 1.0:
            pulse = None
        attack_deadline = (
            resolved_sec - 8.0 if order <= 3
            else applied_sec + 3.0
        )
        attacks = [
            event for event in active_boss_actions
            if event["source"] == target
            and attack_deadline < event["sec"] <= min(resolved_sec, end_sec)
        ]
        if attacks:
            continued_attack_issues.append({
                "player": target,
                "target_order": order,
                "applied_offset": round(applied_sec - start_sec, 3),
                "allowed_until_offset": round(attack_deadline - start_sec, 3),
                "rule": (
                    "前三名可打到超载剩余8秒"
                    if order <= 3 else "点名3秒后不得继续攻击"
                ),
                "first_attack_offset": round(attacks[0]["sec"] - start_sec, 3),
                "hits": len(attacks),
                "damage": sum(event["damage"] for event in attacks),
                "spells": Counter(event["spell"] for event in attacks).most_common(),
            })
        suppression_sec = next((
            moment for moment in suppression_gains.get(target, [])
            if resolved_sec - 0.25 <= moment <= resolved_sec + 0.5
        ), None)
        soaks = [
            event for event in unstable_hits[target]
            if suppression_sec is not None and suppression_sec <= event["sec"] <= suppression_sec + 45
        ]
        post_suppression_attacks = [
            event for event in active_boss_actions
            if suppression_sec is not None
            and event["source"] == target
            and suppression_sec < event["sec"] <= end_sec
        ]
        if suppression_sec is not None and post_suppression_attacks and not soaks:
            no_soak_issues.append({
                "player": target,
                "suppression_offset": round(suppression_sec - start_sec, 3),
                "first_attack_offset": round(post_suppression_attacks[0]["sec"] - start_sec, 3),
                "hits": len(post_suppression_attacks),
                "damage": sum(event["damage"] for event in post_suppression_attacks),
            })
        overload_results.append({
            "player": target,
            "applied_offset": round(applied_sec - start_sec, 3),
            "resolved_offset": round(resolved_sec - start_sec, 3),
            "duration": round(resolved_sec - applied_sec, 3),
            "trigger": "持有者死亡" if death_sec is not None else "15秒读条结束",
            "raid_hit_count": len(pulse["targets"]) if pulse else 0,
            "raid_damage": pulse["damage"] if pulse else 0,
            "average_raid_damage": (
                round(pulse["damage"] / len(pulse["targets"]), 1)
                if pulse and pulse["targets"] else 0
            ),
            "counted_error": (
                pulse["damage"] / len(pulse["targets"]) > 1200
                if pulse and pulse["targets"] else False
            ),
            "soaked": bool(soaks),
            "first_soak_offset": round(soaks[0]["sec"] - start_sec, 3) if soaks else None,
        })
    mark_chained_overloads(overload_results)

    return {
        "start": start,
        "end": end,
        "resistance_scope": "装备、野性印记/赐福、魔法抗性药水、种族被动；低于180的装备检查快照不视为完整值",
        "arcane_resistance": resistance_rows,
        "arcane_protection_missing": [
            player for player in sorted(roster)
            if player not in protection_holders and player not in tanks
        ],
        "arcane_prisons": prisons,
        "overloads": overload_results,
        "continued_attack_issues": continued_attack_issues,
        "no_soak_issues": no_soak_issues,
    }


def build_error_summary(report):
    totals = Counter()
    details = defaultdict(Counter)
    findings = []

    def add(player, boss, issue, weight=1, src=()):
        if not player or player in ("未识别", "责任人未记录", "无法唯一归因"):
            return
        if not present_in(player, boss):
            return
        totals[player] += weight
        details[player]["%s·%s" % (boss, issue)] += weight
        findings.append({
            "player": player,
            "boss": boss,
            "issue": issue,
            "weight": weight,
            "sources": list(src),
        })

    # 暗影诅咒只展示覆盖率，不计错；语言诅咒仅检查麦迪文，
    # 其余诅咒国王低于80%、其他首领低于90%计错。
    for encounter in report["curses"]:
        for curse in encounter["curses"]:
            if curse["is_error"]:
                add(curse["responsible"], encounter["boss"], curse["curse"] + "有断档", src=(encounter, curse))

    for item in report["buff_coverage"]["issues"]:
        if not item["buff"].startswith("强效"):
            continue
        for responsible in item.get("responsible", []):
            add(responsible, "团队Buff", item["buff"] + "断档", src=(item,))

    for item in report["windfury_coverage"]["groups"]:
        if item["is_error"]:
            add(
                item["shaman"],
                "团队Buff",
                "%d队风怒图腾覆盖率低于80%%" % item["group"],
                item["error_weight"],
                src=(item,),
            )

    consumables = report["consumables"]
    for item in consumables["expiration_issues"]:
        add(item["player"], "消耗品", item["name"] + "到期未及时补", src=(item,))
    for item in consumables["demon_slaying_issues"]:
        add(item["player"], item["boss"], "开打未保持屠魔药剂", src=(item,))

    bosses = report["boss_analysis"]
    narmuun = bosses["守护者纳尔穆恩"]
    for item in narmuun["preparation"]:
        for player in item["missing"]:
            add(player, "守护者纳尔穆恩", "开打缺少" + item["item"], src=(item,))
    for item in narmuun["moon_outgoing_by_player"]:
        if item["is_error"]:
            add(item["player"], "守护者纳尔穆恩", "红蓝月伤害别人", src=(item,))
    for item in narmuun["owl_issues"]:
        add(item["player"], "守护者纳尔穆恩", "猫头鹰低血量继续攻击", src=(item,))

    intagos = bosses["魔网观察者因塔苟斯"]
    for item in intagos["early_casters"]:
        add(item["player"], "魔网观察者因塔苟斯", "初始小怪未清先打Boss", src=(item,))
    for affinity in intagos["affinities"]:
        for item in affinity["players"]:
            if item["is_error"]:
                add(item["player"], "魔网观察者因塔苟斯", affinity["affinity"] + "零对应伤害", src=(affinity, item))
    for item in intagos["preparation"]:
        for player in item["missing"]:
            add(player, "魔网观察者因塔苟斯", "开打缺少" + item["item"], src=(item,))

    anomalus = bosses["阿诺玛鲁斯"]
    for player in anomalus["arcane_protection_missing"]:
        add(player, "阿诺玛鲁斯", "开打未吃奥术防护", src=())
    for item in anomalus["overloads"]:
        if item["counted_error"]:
            add(item["player"], "阿诺玛鲁斯", "奥术超载炸到大团", src=(item,))
    for item in anomalus["continued_attack_issues"]:
        add(item["player"], "阿诺玛鲁斯", "中奥术超载超过允许时间仍打Boss", src=(item,))
    for item in anomalus["no_soak_issues"]:
        add(item["player"], "阿诺玛鲁斯", "爆炸后打Boss但未踩圈", src=(item,))

    medivh = bosses["麦迪文的回响"]
    for item in medivh["wrong_interrupts"]:
        add(item["interrupter"], "麦迪文的回响", "错误打断" + item["spell"], src=(item,))
    for item in medivh["priority_interrupt_issues"]:
        if item.get("interrupter") and item["status"] == "打断过早":
            add(item["interrupter"], "麦迪文的回响", item["spell"] + "打断过早", src=(item,))
    for item in medivh["corruption_transmissions"]:
        if item["unique_source"]:
            add(item["sources"][0], "麦迪文的回响", "腐化传染他人", src=(item,))
    for item in medivh["corruption_dispels"]:
        add(item["dispeller"], "麦迪文的回响", "直接驱散麦迪文的腐化", src=(item,))

    king = bosses["国王（国际象棋）"]
    for check in king["opening_add_checks"]:
        for player in check["noncontributors"]:
            add(
                player,
                "国王（国际象棋）",
                "第%d次未攻击%s" % (
                    check["attempt"], check["target"]
                ),
                src=(check,),
            )
    for item in king["mechanic_deaths"]:
        add(item["player"], "国王（国际象棋）", "死于" + item["mechanic"], src=(item,))
    for item in king["late_bows"]:
        add(item["player"], "国王（国际象棋）", "黑暗屈从下跪不及时", src=(item,))
    for item in king["first_charm_issues"]:
        add(item["player"], "国王（国际象棋）", "首次心控未及时自解", src=(item,))

    sanf = bosses["桑夫·塔斯达尔"]
    for item in sanf["rift_feedback_death_issues"]:
        add(item["responsible"], "桑夫·塔斯达尔", "裂隙回馈死亡责任", src=(item,))
    for item in sanf["wrong_dispels"]:
        add(item["caster"], "桑夫·塔斯达尔", "错误解除" + item["removed"], src=(item,))
    for item in sanf["entanglement_issues"]:
        if item["counted_error"]:
            add(item["player"], "桑夫·塔斯达尔", "裂隙纠缠期间未打德莱尼虚无行者", src=(item,))
    for item in sanf["large_add_transformations"]:
        for player in item["responsible"]:
            add(player, "桑夫·塔斯达尔", "大怪成功变身", src=(item,))
    for item in sanf["overflowing_hatreds"]:
        for player in item["direct_deaths"]:
            add(player, "桑夫·塔斯达尔", "死于仇恨溢出", src=(item,))
    for wave in sanf["shadow_waves"]:
        for value in wave["delayed"]:
            add(value.rsplit(" ", 1)[0], "桑夫·塔斯达尔", "失落暗影转火过晚", src=(wave,))
        for player in wave["missed"]:
            add(player, "桑夫·塔斯达尔", "失落暗影未转火", src=(wave,))

    rupturan = bosses["破碎者鲁普图兰"]
    for item in rupturan["eruption_deaths"]:
        add(item["player"], "破碎者鲁普图兰", "死于摇摇欲坠喷发", src=(item,))
    for item in rupturan["low_health_boss_issues"]:
        add(item["player"], "破碎者鲁普图兰", "5%阶段仍攻击Boss", src=(item,))
    for item in rupturan["living_fragment_kills"]:
        for player in item["non_attackers"]:
            add(player, "破碎者鲁普图兰", "活体碎块致死窗口未转火", src=(item,))
    drains = {item["player"]: item for item in rupturan["mana_drains"]}
    for player in rupturan["mana_noncontributors"]:
        add(player, "破碎者鲁普图兰", "恶魔之心未抽蓝", src=tuple(item for item in (drains.get(player),) if item))

    kruul = bosses["库鲁尔"]
    for item in kruul["high_stack_incidents"]:
        for player in item["responsible_tanks"]:
            add(player, "库鲁尔", "未接手导致冷漠打击达到7层", src=(item,))
    for item in kruul["mark_explosions"]:
        add(item["caster"], "库鲁尔", "解除大领主印记炸到人", src=(item,))
    for item in kruul["infernal_issues"]:
        add(item["player"], "库鲁尔", "第一阶段非T攻击地狱火", src=(item,))

    mephistroth = bosses["孟菲斯托斯"]
    for item in mephistroth["shackle_explosions"]:
        add(
            item["trigger"],
            "孟菲斯托斯",
            "提前挣脱军团镣铐",
            item["hits"],
            src=(item,),
        )
    for wave in mephistroth["crawler_waves"]:
        if wave["mana_drain_counts_as_error"]:
            for player in wave["ranged_noncontributors"]:
                add(player, "孟菲斯托斯", "噩梦爬行者吸蓝前未转火", src=(wave,))
    for item in mephistroth["forbidden_boss_attacks"]:
        add(item["player"], "孟菲斯托斯", "55%停手阶段仍攻击Boss", src=(item,))

    ranking = []
    all_players = report["metadata"]["roster"]
    for player in sorted(all_players, key=lambda name: (-totals[name], name)):
        count = totals[player]
        ranking.append({
            "player": player,
            "count": count,
            "details": [
                {"issue": issue, "count": issue_count}
                for issue, issue_count in sorted(
                    details[player].items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
        })

    wipe_causes = []
    for cause in WIPE_CAUSES:
        boss_report = bosses.get(cause["boss"], {})
        attempt = next((
            item for item in boss_report.get("attempts", [])
            if item.get("attempt") == cause["attempt"]
        ), {})
        transformation = next((
            item for item in boss_report.get("large_add_transformations", [])
            if item.get("attempt") == cause["attempt"]
        ), {})
        wipe_causes.append({
            "encounter": cause["encounter"],
            "responsible": cause["responsible"],
            "involved": transformation.get("responsible", []),
            "error": cause["error"],
            "result": cause["result"],
            "timeline": attempt.get("key_mechanic_timeline", []),
            "deaths": attempt.get("deaths", []),
        })
    report["_findings"] = findings
    return {
        "method": "只统计能明确归因到个人的逐Boss机制、诅咒分工、团队Buff分工、准备与消耗品问题；桑夫大怪成功变身时全体物理近战各计1次；国王之怒致死计个人错误，但不作为灭团原因；噩梦爬行者按有效波次计错，挣脱镣铐按实际炸到的人数计次，其余同一人同一波/同一事件记1次，不按伤害跳数重复。团队性问题或责任人无法唯一确定的事件不计入个人排行。",
        "ranking": ranking,
        "wipe_causes": wipe_causes,
    }


def analyze(settings):
    """返回 (report, findings, rows, name_issues)。不写任何文件。"""
    global PRESENCE
    configure(settings)
    rows = parse_lines()
    roster = build_roster(rows)
    PRESENCE = compute_presence(rows, roster)
    dps, parsed_damage = analyze_dps(rows, roster)
    roles = analyze_roles(rows, roster, parsed_damage, dps["players"])
    role_by_name = dict((item["name"], item["role"]) for item in roles)
    for item in dps["players"]:
        role = role_by_name.get(item["name"])
        if role in ("坦克", "物理近战", "物理远程"):
            item["group"] = "物理"
        elif role == "法术远程":
            item["group"] = "法系"
    buffs = analyze_buffs(rows, roster, roles)
    sanf = analyze_sanf(rows, boss_roster(roster, "桑夫·塔斯达尔"), parsed_damage, roles)
    dispel_candidates = analyze_dispels(rows, roster, parsed_damage)
    report = {
        "metadata": {
            "source": LOG_PATH,
            "date": DATE,
            "raid_start": RAID_START,
            "raid_end": RAID_END,
            "roster_size": len(roster),
            "roster": sorted(roster),
            "limitations": [
                "旧版中文战斗日志不含GUID、职业字段、最大生命值或血量百分比。",
                "职业与法系/物理分类由实际技能构成推断；近战攻击萨满、非坦克非治疗圣骑士按物理近战，猎人按实际近战/远程技能判定。",
                "大多数团队Buff获得事件不记录施法者；骑士祝福按高级日志整场施放次数最多的祝福推定责任人。",
                "未提供本周八队分组；普通Buff按玩家实际失效与重新获得记录检查及时性，风怒覆盖不做可靠判定。",
                "错误驱散为关联筛查：解除奥术压力后0.75秒内至少3人各承受800以上奥术能量伤害；大领主印记解除前后0.1秒内出现单次5000以上的高伤暗影新星即计错，普通约1300的暗影新星排除。",
            ],
        },
        "roles": roles,
        "dps": dps,
        "buffs": buffs,
        "buff_coverage": analyze_buff_coverage(buffs, parsed_damage, roster, roles),
        "windfury_coverage": analyze_windfury_coverage(
            rows, parsed_damage, roster, roles
        ),
        "curses": analyze_curses(rows, parsed_damage, roster),
        "dispel_candidates": dispel_candidates,
        "sanf_wrong_dispels": sanf,
        "consumables": analyze_consumables(rows, roster, parsed_damage, roles),
        "boss_analysis": {
            "守护者纳尔穆恩": analyze_narmuun(rows, boss_roster(roster, "守护者纳尔穆恩"), parsed_damage, roles),
            "魔网观察者因塔苟斯": analyze_intagos(
                rows, boss_roster(roster, "魔网观察者因塔苟斯"), parsed_damage, dps["players"], roles
            ),
            "阿诺玛鲁斯": analyze_anomalus(rows, boss_roster(roster, "阿诺玛鲁斯"), parsed_damage, roles),
            "麦迪文的回响": analyze_medivh(rows, boss_roster(roster, "麦迪文的回响")),
            "国王（国际象棋）": analyze_king(
                rows, boss_roster(roster, "国王（国际象棋）"), parsed_damage, roles
            ),
            "桑夫·塔斯达尔": sanf,
            "破碎者鲁普图兰": analyze_rupturan(rows, boss_roster(roster, "破碎者鲁普图兰"), parsed_damage, roles),
            "库鲁尔": analyze_kruul(
                rows, boss_roster(roster, "库鲁尔"), parsed_damage, roles, dispel_candidates
            ),
            "孟菲斯托斯": analyze_mephistroth(
                rows, boss_roster(roster, "孟菲斯托斯"), parsed_damage, roles
            ),
        },
    }
    report["error_summary"] = build_error_summary(report)
    findings = report.pop("_findings")
    issues = [dict(item) for item in NAME_ISSUES]
    for item in issues:
        item.pop("key")
    return report, findings, rows, issues
