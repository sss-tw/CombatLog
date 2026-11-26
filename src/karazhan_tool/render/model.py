from __future__ import print_function

import io
import json
import os
import sys
from html import escape


# 经人工或 AI 复核的当周结论文字，由日期配置 display_notes 提供。
NOTES = {}

UNAVAILABLE_TEXT = u"未提供本周八队分组，无法可靠判定"

FIELD_LABELS = {
    "player": "玩家", "name": "名称", "class": "职业", "role": "职责",
    "count": "次数", "damage": "伤害", "dps": "每秒伤害", "result": "结论",
    "status": "状态", "attempt": "尝试", "start": "开始", "end": "结束",
    "duration": "持续时间", "offset": "开打后", "target": "目标",
    "caster": "施法者", "spell": "技能", "removed": "移除效果",
    "responsible": "责任人", "error": "问题", "encounter": "战斗",
    "issue": "错误项", "details": "明细", "role": "职责", "evidence": "判定依据",
    "healing_actions": "治疗动作", "tank_actions": "坦克动作",
    "group": "分组", "top_skills": "主要技能", "buff": "增益效果",
    "provider_candidates": "可施放者", "assigned_providers": "推定责任者",
    "item": "检查项", "log_aura": "日志效果", "missing": "缺失玩家",
    "hits": "命中", "ticks": "跳数", "amount": "数值", "reason": "原因",
    "resolution": "结算", "wave": "波次", "deaths": "死亡",
    "first_offset": "首次出现", "death_offset": "死亡时间",
    "applied_offset": "获得时间", "removed_offset": "移除时间",
    "delay": "延迟", "outcome": "结果", "rule": "规则", "kind": "类型",
    "available": "数据可用", "scope": "统计范围", "method": "口径",
    "ts": "时间", "line": "日志行", "aura": "效果", "dispeller": "驱散者",
    "involved": "涉及人员", "timeline": "时间线", "rank": "排名",
    "healing": "治疗动作", "damage_actions": "伤害动作",
    "hunter_melee_damage": "猎人近战伤害", "hunter_ranged_damage": "猎人远程伤害",
    "schools": "伤害类型", "boss": "首领", "target_scope": "目标范围",
    "curse": "诅咒", "casters": "施放者", "casts": "施放次数",
    "first_cast": "首次施放", "first_delay": "首次延迟",
    "uptime_pct": "全程覆盖率", "targetable_uptime_pct": "可攻击阶段覆盖率",
    "gap_intervals": "断档区间", "total_gap": "断档总时长",
    "error_rule": "判错规则", "is_error": "是否计错",
    "dispel": "驱散技能", "hit_players": "命中玩家",
    "raid_damage_075s": "0.75秒内全团伤害", "players": "玩家名单",
    "assumption": "统计假设", "gap_threshold": "断档阈值",
    "expiration_issues": "到期未补问题", "expired": "失效时间",
    "regained": "重新获得时间", "combat_delay": "战斗内延迟",
    "death_issues": "死亡后未补问题", "death": "死亡时间",
    "next_pull": "下次开怪", "known_profile": "已知持续时间",
    "regained_before_pull": "开怪前已补回",
    "missing_combat_durations": "缺少战斗持续时间",
    "unknown_combat_duration": "持续时间未知", "note": "说明",
    "demon_slaying_melee": "近战屠魔药剂", "demon_slaying_issues": "屠魔药剂问题",
    "boss_start": "首领开战时间", "assigned": "责任人",
    "damaged_group": "受伤队伍", "is_main_tank": "是否主坦",
    "owl": "猫头鹰", "spells": "技能构成",
    "affinity_history": "亲和历史记录", "affinity": "亲和",
    "allowed_school": "允许伤害类型", "start_offset": "开始时间",
    "end_offset": "结束时间", "count_zero_errors": "零伤害是否计错",
    "curse_summary": "诅咒汇总", "total": "合计",
    "display_total": "显示总值", "gear": "装备", "potion": "药剂",
    "racial": "种族能力", "detail": "明细", "gear_snapshot": "装备快照",
    "verified": "是否核实", "dispelled": "是否驱散",
    "resolved_offset": "结算时间", "trigger": "触发者",
    "raid_hit_count": "全团命中人数", "raid_damage": "全团伤害",
    "average_raid_damage": "人均全团伤害", "counted_error": "是否计错",
    "soaked": "是否踩圈", "first_soak_offset": "首次踩圈时间",
    "first_attack_offset": "首次继续攻击", "suppression_offset": "压制时间",
    "language_curse": "语言诅咒", "interrupt_offset": "打断时间",
    "interrupter": "打断者", "interrupt_spell": "打断技能",
    "elapsed": "耗时", "expected": "应负责人员", "targets": "目标",
    "first_attempt_bishop_fear": "主教恐惧检查", "responsibility": "责任范围",
    "eligible_roles": "适用职责", "window_end_offset": "窗口结束时间",
    "window_end_reason": "窗口结束原因", "counts_errors": "是否计入错误",
    "eligible_count": "适用人数", "results": "结果明细",
    "noncontributors": "未参与人员", "mechanic": "机制",
    "damage_offset": "伤害时间", "died": "是否死亡",
    "key_mechanic_timeline": "关键机制时间线", "review_note": "复核说明",
    "window": "时间窗口", "add_window": "小怪在场窗口",
    "cast_offset": "施放时间", "logged_targets": "日志目标",
    "damaged_players": "受伤玩家", "timely": "及时处理",
    "delayed": "处理过晚", "missed": "未处理",
    "mana_noncontributors": "未参与抽蓝人员", "energy_burst": "能量爆发",
    "sec": "时间（秒）", "stack": "层数",
    "holding_taunter": "当前接怪坦克", "holding_taunt_spell": "接怪嘲讽技能",
    "holding_taunt_offset": "接怪嘲讽时间", "missed_taunter": "漏嘲坦克",
    "late_taunt_spell": "迟到嘲讽技能", "late_taunt_offset": "迟到嘲讽时间",
    "late_by": "迟到时长", "applied_sec": "获得时间（秒）",
    "resolved_sec": "解除时间（秒）", "spawn_offset": "生成时间",
    "mana_drain_started": "是否开始吸蓝", "mana_drain_success": "是否吸到法力",
    "mana_drain_counts_as_error": "吸蓝是否计错",
    "ignored_below_thirty": "30%以下豁免",
    "mana_drain_start_offset": "开始吸蓝时间",
    "mana_drain_hit_offset": "吸蓝命中时间",
    "ranged_noncontributors": "未转火远程",
    "eye_duty_exempt_players": "恶魔之眼职责豁免",
    "ranged_contributors": "参与转火远程", "last_death_offset": "最后击杀时间",
    "historical_evidence": "历史日志机制证据",
    "explicit_sources": "明确来源", "paladin_blessing_assignments": "骑士祝福分工",
    "provider_skill_counts": "责任人施放统计", "losses": "断档记录",
    "rebuffed": "已补回", "median_delay": "延迟中位数",
    "max_delay": "最长延迟", "slow_rebuffs": "补回过慢",
    "boss_slow_rebuffs": "首领战补回过慢", "not_rebuffed": "未补回",
    "gain": "获得时间", "loss": "失效时间", "event": "事件",
    "interval": "区间", "mode": "判定方式", "unit": "单位",
    "until_end": "持续至战斗结束", "affected": "受影响者",
    "sources": "来源", "ambiguous": "是否存在歧义",
    "blessing": "祝福", "counts": "次数统计",
    "dominant_candidates": "主要责任候选", "coverage_start_offset": "覆盖统计起点",
    "targetable_duration": "可攻击时长", "dispel_spell": "驱散技能",
    "moon_error_threshold": "互伤判错阈值", "moon_exempt_main_tank": "主坦是否豁免",
    "moon_main_tank_method": "主坦判定方式", "moon_method": "红蓝月统计方式",
    "initial_add_deaths": "初始小怪死亡时间", "adds_clear_offset": "小怪清完时间",
    "confirmed": "是否确认", "class_rule": "职业规则",
    "applicable_count": "适用人数", "removed_within_10s_count": "10秒内解除次数",
    "long_count": "长时间未解除次数", "long_threshold_seconds": "超时阈值（秒）",
    "resistance_scope": "抗性统计范围", "interrupt_rule": "打断规则",
    "corruption_attribution_limit": "腐化传播归因时限", "spell_id": "技能编号",
    "max_rank": "最高等级", "is_max_rank": "是否最高等级",
    "black_water_name": "黑水技能名", "first_charm_rule": "首次心控判定规则",
    "fear_offset": "恐惧时间", "affected_count": "受影响人数",
    "ranged_results": "远程转火结果", "voidwalker_name": "虚无行者名称",
    "shadow_rule": "失落暗影规则", "phase_two_offset": "二阶段开始时间",
    "five_pct_method": "5%血量判定方式", "five_pct_offset": "5%血量时间",
    "living_fragment_responsibility": "活体碎块职责",
    "occurred": "是否发生", "high_stack_aura": "高层效果",
    "phase_one_method": "一阶段判定方式", "phase_one_end_offset": "一阶段结束时间",
    "crawler_failure_rule": "噩梦爬行者判错规则",
    "crawler_ignore_below_boss_health_pct": "爬行者豁免血量阈值",
    "thirty_percent_offset": "30%血量时间",
    "fifty_five_method": "55%血量判定方式", "fifty_five_offset": "55%血量时间",
    "next_crystal_offset": "下一次水晶时间", "eye_name": "眼睛名称",
    "effect": "效果", "bait": "引眼人员", "exempt_from_crawler": "爬行者检查豁免",
    "bait_counts": "引眼次数", "dispeller_counts": "驱散次数",
    "episodes": "每次处理记录", "shackle": "镣铐机制", "crystal": "水晶机制",
}

SECTION_LABELS = {
    "preparation": "开打准备", "moon_outgoing_by_player": "红蓝月互伤",
    "curse_issues": "诅咒问题", "decurse_counts": "解诅咒次数",
    "owl_issues": "猫头鹰低血量攻击", "early_casters": "初始小怪未清先打首领",
    "affinities": "亲和机制", "curse_results": "魔鳞诅咒明细",
    "arcane_resistance": "奥术抗性", "arcane_protection_missing": "未吃奥术防护",
    "arcane_prisons": "奥术监牢", "overloads": "奥术超载",
    "continued_attack_issues": "超载后继续攻击", "no_soak_issues": "未踩地圈",
    "wrong_interrupts": "错误打断", "priority_interrupt_issues": "重点技能打断",
    "doom_dispels": "灾祸驱散", "corruption_boss_applications": "腐化直接点名",
    "corruption_transmissions": "腐化传播", "corruption_dispels": "腐化驱散",
    "attempts": "尝试结果", "opening_add_checks": "开场小怪转火",
    "mechanic_deaths": "机制致死", "late_bows": "黑暗屈从",
    "first_charm_issues": "首次心控自解", "wipe_summaries": "灭团时间线",
    "second_attempt_death_sequence": "第二次尝试死亡链",
    "mass_curse_waves": "裂隙诅咒波次", "wrong_dispels": "错误解除",
    "rift_feedback_death_issues": "裂隙回馈死亡责任",
    "voidwalker_windows": "虚无行者在场窗口", "entanglement_issues": "裂隙纠缠",
    "tracker_waves": "裂隙追踪者", "rift_feedbacks": "裂隙回馈",
    "overflowing_hatreds": "仇恨溢出", "shadow_waves": "失落暗影",
    "eruption_deaths": "喷发致死", "living_stone_windows": "活体石块窗口",
    "low_health_boss_issues": "低血量继续攻击首领",
    "living_fragment_kills": "活体碎块击杀", "mana_drains": "恶魔之心抽蓝",
    "high_stack_incidents": "冷漠打击高层", "mark_explosions": "大领主印记爆炸",
    "observed_tanks": "可观察坦克", "infernal_issues": "非坦克攻击地狱火",
    "mechanics": "机制规则", "curse_dispels": "诅咒解除",
    "doom_applications": "外域的末日", "doom_deaths": "末日致死",
    "shackle_explosions": "军团镣铐异常挣脱", "crawler_waves": "噩梦爬行者",
    "forbidden_boss_attacks": "55% 停手阶段攻击首领",
    "crystal_waves": "地狱之怒碎片", "eye_duty": "恶魔之眼职责",
    "assumption": "统计假设", "gap_threshold": "断档阈值",
    "expiration_issues": "到期未补问题", "death_issues": "死亡后未补问题",
    "demon_slaying_melee": "近战屠魔药剂", "demon_slaying_issues": "屠魔药剂问题",
    "moon_boss_melee_by_tank": "红蓝月期间坦克承伤",
    "affinity_history": "亲和历史记录", "curse_summary": "诅咒汇总",
    "language_curse": "语言诅咒", "first_attempt_bishop_fear": "主教恐惧检查",
    "key_mechanic_timeline": "关键机制时间线", "review_note": "复核说明",
    "mana_noncontributors": "未参与抽蓝人员", "energy_burst": "能量爆发",
    "historical_evidence": "历史日志机制证据",
}


def read_json(path):
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_text(path, content):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def format_duration(seconds):
    seconds = int(round(float(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return u"%d小时%d分%02d秒" % (hours, minutes, secs)
    return u"%d分%02d秒" % (minutes, secs)


def compact(value):
    if value is None:
        return "-"
    if value is True:
        return "是"
    if value is False:
        return "否"
    if isinstance(value, float):
        return ("%.3f" % value).rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        if not value:
            return "无"
        if all(not isinstance(item, (dict, list, tuple)) for item in value):
            return "、".join(compact(item) for item in value)
        return "；".join(compact(item) for item in value)
    if isinstance(value, dict):
        return "；".join(
            "%s：%s" % (FIELD_LABELS.get(key, key), compact(item))
            for key, item in value.items()
        ) or "无"
    return (
        str(value)
        .replace("Boss", "首领")
        .replace("Buff", "增益")
        .replace("DPS", "每秒伤害")
        .replace("非T", "非坦克")
        .replace("Infernal", "地狱火")
    )


def table_from_value(title, value):
    if isinstance(value, list):
        if not value:
            return {"title": title, "headers": ["结果"], "rows": [["无记录"]]}
        if all(isinstance(item, dict) for item in value):
            keys = []
            for item in value:
                for key in item:
                    if key not in keys:
                        keys.append(key)
            return {
                "title": title,
                "headers": [FIELD_LABELS.get(key, key) for key in keys],
                "rows": [[compact(item.get(key)) for key in keys] for item in value],
            }
        return {
            "title": title,
            "headers": ["记录"],
            "rows": [[compact(item)] for item in value],
        }
    if isinstance(value, dict):
        return {
            "title": title,
            "headers": ["项目", "内容"],
            "rows": [[FIELD_LABELS.get(key, key), compact(item)] for key, item in value.items()],
        }
    return {"title": title, "headers": ["内容"], "rows": [[compact(value)]]}


def chinese_attempt(index):
    names = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    return names[index] if index < len(names) else str(index)


def attempts_text(attempts):
    if not attempts:
        return "日志未记录尝试结果。"
    details = []
    for item in attempts:
        number = item.get("attempt", len(details) + 1)
        details.append("第%s次%s" % (chinese_attempt(int(number)), item.get("result", "结果未记录")))
    return "共%d次尝试：%s。" % (len(attempts), "、".join(details))


def filtered_error_ranking(report):
    buff_available = report.get("buff_coverage", {}).get("available", True)
    wind_available = report.get("windfury_coverage", {}).get("available", True)
    result = []
    for entry in report["error_summary"]["ranking"]:
        details = []
        for detail in entry.get("details", []):
            issue = detail.get("issue", "")
            if not buff_available and issue.startswith("团队Buff·"):
                continue
            if not wind_available and ("风怒" in issue or "风怒图腾" in issue):
                continue
            details.append(detail)
        count = sum(item.get("count", 0) for item in details)
        result.append({
            "player": entry["player"],
            "count": count,
            "details": (
                "；".join(
                    "%s×%s" % (item["issue"], compact(item["count"])) for item in details
                )
                if details else "没犯错误"
            ),
        })
    result.sort(key=lambda item: (-item["count"], item["player"]))
    for index, item in enumerate(result, 1):
        item["rank"] = index
    return result


def find_curse(report, boss, curse_name):
    for encounter in report.get("curses", []):
        if encounter.get("boss") != boss:
            continue
        for curse in encounter.get("curses", []):
            if curse.get("curse") == curse_name:
                return curse
    return None


def boss_conclusions(report, name, data):
    lines = []
    if data.get("start"):
        lines.append("实际开怪时间：%s；结束时间：%s。" % (data["start"], data.get("end", "未记录")))
    if name == "国王（国际象棋）":
        lines.append(attempts_text(data.get("attempts", [])))
        fear = data.get("first_attempt_bishop_fear") or {}
        lines.append("主教恐惧检查：%s。" % fear.get("status", "无可用记录"))
        if data.get("wipe_summaries"):
            lines.append("灭团记录以本周 JSON 的时间线为准。")
        else:
            lines.append("本周没有国王灭团时间线，不生成旧场次的灭团或死亡链结论。")
    elif name == "桑夫·塔斯达尔":
        lines.append(attempts_text(data.get("attempts", [])))
        causes = [
            item for item in report["error_summary"].get("wipe_causes", [])
            if item.get("encounter", "").startswith(name)
        ]
        if causes:
            lines.append("灭团结论：" + "；".join(
                "%s：%s（%s）" % (
                    item.get("responsible", "涉及者未记录"),
                    item.get("error", "原因未记录"),
                    item.get("result", "后果未记录"),
                ) for item in causes
            ))
        feedbacks = data.get("rift_feedbacks", [])
        if feedbacks:
            total_hits = sum(
                len(item.get("damaged_players", []))
                if isinstance(item.get("damaged_players"), list)
                else int(item.get("damaged_players", 0))
                for item in feedbacks
            )
            lines.append("裂隙回馈记录：%d次，累计命中%d人；机制明细见表。" % (len(feedbacks), total_hits))
        hatred_deaths = sum(len(item.get("deaths", [])) for item in data.get("overflowing_hatreds", []))
        lines.append("仇恨溢出共%d次，附近死亡记录%d人次。" % (
            len(data.get("overflowing_hatreds", [])), hatred_deaths
        ))
    elif name == "麦迪文的回响":
        curse = find_curse(report, name, "语言诅咒")
        if curse:
            coverage = curse.get("targetable_uptime_pct")
            if coverage is None:
                coverage = curse.get("uptime_pct")
            lines.append("本周语言诅咒覆盖率%s%%，总断档%s秒，责任人：%s。" % (
                compact(coverage), compact(curse.get("total_gap", 0)),
                compact(curse.get("responsible")),
            ))
        language = data.get("language_curse", {})
        if language:
            lines.append("技能等级核验：%s。" % language.get("evidence", compact(language)))
    elif name == "破碎者鲁普图兰":
        lines.append("一阶段实际开怪为%s；二阶段从开打后%s秒开始。" % (
            data.get("start", "未记录"), compact(data.get("phase_two_offset"))
        ))
        burst = data.get("energy_burst", {})
        lines.append("能量爆发：%s。" % (
            "发生，%s人命中、%s伤害" % (compact(burst.get("hits")), compact(burst.get("damage")))
            if burst.get("occurred") else "本周未发生"
        ))
    elif name == "孟菲斯托斯":
        shackles = data.get("shackle_explosions", [])
        lines.append("军团镣铐异常挣脱：%d次。" % len(shackles))
        crystals = data.get("crystal_waves", [])
        if crystals:
            lines.append("水晶阶段：" + "；".join(
                "第%s轮%s" % (compact(item.get("wave")), item.get("result", "结果未记录"))
                for item in crystals
            ))
        eye = data.get("eye_duty") or {}
        lines.append("恶魔之眼职责：引眼%s，陪同驱散%s。" % (
            eye.get("bait") or "未识别", eye.get("dispeller") or "未识别"
        ))
    return lines


def callout(title, text, tone="info"):
    return {"title": title, "text": text, "tone": tone}


def format_offset(value):
    if value is None:
        return "-"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return compact(value)
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    if minutes:
        return "+%d:%06.3f" % (minutes, remainder)
    return "+%.3f秒" % seconds


def spell_summary(value):
    if not value:
        return "-"
    return "、".join("%s×%s" % (item[0], item[1]) for item in value)


def selected_table(title, rows, columns, empty="无问题"):
    if not rows:
        return {"title": title, "headers": ["结论"], "rows": [[empty]]}
    output = []
    for item in rows:
        row = []
        for getter, label in columns:
            if callable(getter):
                value = getter(item)
            elif isinstance(item, dict):
                value = item.get(getter)
            else:
                value = item
            if isinstance(getter, str) and (
                getter == "offset" or getter.endswith("_offset")
            ):
                value = format_offset(value)
            row.append(compact(value))
        output.append(row)
    return {
        "title": title,
        "headers": [label for getter, label in columns],
        "rows": output,
    }


def aggregate_rows(rows, key_fields, list_field=None):
    counts = {}
    for item in rows:
        values = []
        for key in key_fields:
            values.append(item.get(key))
        if list_field:
            listed = item.get(list_field) or []
            if not listed:
                listed = ["未记录"]
            for listed_item in listed:
                key = tuple(values + [listed_item])
                counts[key] = counts.get(key, 0) + 1
        else:
            key = tuple(values)
            counts[key] = counts.get(key, 0) + 1
    result = []
    for key, count in counts.items():
        row = {"count": count}
        for index, field in enumerate(key_fields):
            row[field] = key[index]
        if list_field:
            row[list_field] = key[-1]
        result.append(row)
    return sorted(result, key=lambda item: (-item["count"], compact(item.get(key_fields[0]))))


def note(key, default):
    return NOTES.get(key, default)


def build_model(report, notes=None):
    global NOTES
    NOTES = dict(notes or {})
    metadata = report["metadata"]
    dps = report["dps"]
    elapsed = dps.get("elapsed_time") or 0
    ranking = filtered_error_ranking(report)
    wipe_causes = report["error_summary"].get("wipe_causes", [])
    bosses = report["boss_analysis"]
    role_by_name = dict(
        (item.get("name"), item.get("role")) for item in report.get("roles", [])
    )
    stats = [
        ["日期", metadata["date"]],
        ["开团时间", metadata["raid_start"]],
        ["团队人数", metadata["roster_size"]],
        ["有伤害记录人数", len(dps.get("players", []))],
        ["活跃战斗时间", format_duration(dps["active_combat_time"])],
        ["重点驱散数", len(report.get("dispel_candidates", []))],
        ["副本总时长", format_duration(elapsed)],
    ]

    sections = []
    sections.append({
        "title": "错误总览",
        "notes": [
            callout(
                "先看灭团责任链",
                note("wipe_chain", "本周没有灭团。" if not wipe_causes else "；".join(
                    "%s：%s" % (item.get("encounter"), item.get("error")) for item in wipe_causes
                )),
                "danger",
            ),
            callout(
                "个人排行口径",
                compact(report["error_summary"]["method"])
                + " 普通增益按玩家实际失效与补回时间展示；风怒因缺少八队分组不计入个人排行。",
                "warning",
            ),
        ],
        "tables": [
            selected_table("灭团原因", wipe_causes, [
                ("encounter", "战斗"), ("responsible", "责任归类"),
                ("error", "原因"), ("result", "后果"),
            ]),
            selected_table("个人错误次数排行", ranking, [
                ("rank", "排名"), ("player", "玩家"),
                ("count", "次数"), ("details", "构成"),
            ]),
        ],
    })

    top_dps = []
    for index, item in enumerate(dps.get("players", [])[:12], 1):
        row = dict(item)
        row["rank"] = index
        top_dps.append(row)
    sections.append({
        "title": "总览",
        "notes": [
            callout(
                "本周数据范围",
                "只分析%d月%d日%s至%s的卡塔赞之塔。共%d名到场，%d人有伤害事件；宠物伤害归主人。" % (
                    int(metadata["date"][5:7]), int(metadata["date"][8:10]),
                    metadata["raid_start"][:8], metadata["raid_end"][:8],
                    metadata["roster_size"], len(dps.get("players", [])),
                ),
            ),
            callout(
                "日志限制",
                "旧版中文战斗日志不含单位唯一标识、最大生命值和实时血量百分比；"
                "涉及血量阈值的机制均使用本体累计承伤倒推，并在对应首领章节说明。",
                "warning",
            ),
        ],
        "tables": [
            selected_table("全副本综合伤害前12", top_dps, [
                ("rank", "排名"), ("name", "玩家"), ("class", "职业"),
                ("damage", "总伤害"), ("dps", "每秒伤害"),
                ("top_skills", "主要技能"),
            ]),
        ],
    })

    sections.append({
        "title": "全团职责判定",
        "notes": [
            callout(
                "职责先于职业",
                "根据本周实际释放的坦克、治疗和伤害技能逐人判定，顺序为坦克、治疗、输出类型；"
                "人数不预设。治疗不承担主动攻击小怪的机制责任，猎人若全程使用近战技能则按近战处理。",
            ),
        ],
        "tables": [
            selected_table("%d人职责" % len(report.get("roles", [])), report.get("roles", []), [
                ("name", "玩家"), ("class", "职业"), ("role", "职责"),
                ("healing_actions", "治疗动作"), ("tank_actions", "坦克动作"),
                (lambda item: spell_summary(item.get("evidence")), "判定依据"),
            ]),
        ],
    })

    physical = []
    caster = []
    for index, item in enumerate(dps.get("players", []), 1):
        row = dict(item)
        row["rank"] = index
        row["role"] = role_by_name.get(item.get("name"), "未判定")
        if item.get("group") == "物理":
            physical.append(row)
        else:
            caster.append(row)
    damage_columns = [
        ("rank", "总排名"), ("name", "玩家"), ("class", "职业"),
        ("role", "职责"), ("damage", "总伤害"), ("dps", "每秒伤害"),
        ("top_skills", "主要技能"),
    ]
    sections.append({
        "title": "伤害统计",
        "notes": [
            callout(
                "统计口径",
                "总伤害包含全部小怪和首领；每秒伤害等于总伤害除以全队活跃战斗时间。"
                "混合职业按实际技能构成归类。",
            ),
        ],
        "tables": [
            selected_table("物理职业", physical, damage_columns),
            selected_table("法系职业", caster, damage_columns),
        ],
    })

    blessing_assignments = {}
    druid_casts = {}
    for item in report.get("buffs", []):
        if item.get("paladin_blessing_assignments"):
            blessing_assignments = item["paladin_blessing_assignments"]
        if item.get("buff") == "野性印记/野性赐福":
            druid_casts = item.get("provider_skill_counts") or {}
    blessing_rows = []
    for player, assignment in blessing_assignments.items():
        blessing_rows.append({
            "player": player,
            "blessing": assignment.get("blessing"),
            "counts": assignment.get("counts"),
            "ambiguous": assignment.get("ambiguous"),
        })
    blessing_rows.sort(key=lambda item: item["player"])
    druid_rows = [{"player": player, "casts": casts} for player, casts in sorted(druid_casts.items())]
    buff_gap_rows = report.get("buff_coverage", {}).get("issues", [])
    windfury = report.get("windfury_coverage", {})
    sections.append({
        "title": "团队增益",
        "notes": [
            callout(
                "补Buff及时性",
                "不依赖队伍推断，直接按每名玩家的增益失效到重新获得计算；纯脱战时间不累计，"
                "战斗内缺失超过60秒才列出。没有八队分组时按玩家展示，不强行合并为小队。"
                "骑士祝福只有王者、拯救、力量、智慧断档计错，光明等其余祝福只展示。",
            ),
            callout(
                "风怒覆盖仍需分组",
                windfury.get("reason") or "已按近战队伍统计风怒图腾覆盖率。",
                "warning",
            ),
        ],
        "tables": [
            selected_table("骑士祝福分工", blessing_rows, [
                ("player", "骑士"), ("blessing", "主要负责祝福"),
                ("counts", "施放统计"), ("ambiguous", "是否存在歧义"),
            ]),
            selected_table("野性印记 / 野性赐福施放", druid_rows, [
                ("player", "德鲁伊"), ("casts", "施放次数"),
            ]),
            selected_table("战斗内缺失超过60秒", buff_gap_rows, [
                ("buff", "增益"), ("mode", "判定方式"), ("unit", "玩家/队伍"),
                ("affected", "受影响者"), ("interval", "缺失阶段"),
                ("duration", "战斗内缺失（秒）"), ("until_end", "持续至结束"),
                ("counts_error", "是否计错"),
            ]),
        ],
    })

    curse_rows = []
    for encounter in report.get("curses", []):
        for curse in encounter.get("curses", []):
            curse_rows.append({
                "boss": encounter.get("boss"),
                "target_scope": encounter.get("target_scope"),
                "curse": curse.get("curse"),
                "responsible": curse.get("responsible"),
                "coverage": curse.get("targetable_uptime_pct"),
                "gap": curse.get("total_gap"),
                "error_rule": curse.get("error_rule"),
                "is_error": curse.get("is_error"),
            })
    sections.append({
        "title": "术士诅咒",
        "notes": [
            callout(
                "覆盖率计错规则",
                "每场开打后第2秒开始计算。暗影诅咒只展示覆盖率、不计错；语言诅咒只检查麦迪文，"
                "出现0.5秒以上实际断档即计错。其余诅咒国王低于80%计错，其他首领低于90%计错。",
            ),
        ],
        "tables": [
            selected_table("各首领诅咒覆盖", curse_rows, [
                ("boss", "首领"), ("target_scope", "统计目标"), ("curse", "诅咒"),
                ("responsible", "责任人"), ("coverage", "覆盖率（%）"),
                ("gap", "断档（秒）"), ("error_rule", "计错规则"),
                ("is_error", "是否计错"),
            ]),
        ],
    })

    sections.append({
        "title": "重点驱散",
        "notes": [
            callout(
                "关联筛查口径",
                "奥术压力只列解除后0.75秒内至少3人各承受800以上奥术能量伤害的事件。"
                "大领主印记解除前后0.1秒内出现单次5000以上的高伤暗影新星即计错；"
                "普通约1300的暗影新星排除。",
                "warning",
            ),
        ],
        "tables": [
            selected_table("重点机制驱散", report.get("dispel_candidates", []), [
                ("ts", "时间"), ("encounter", "战斗"), ("caster", "驱散者"),
                ("target", "目标"), ("removed", "移除效果"),
                ("hit_players", "炸到人数"), ("raid_damage_075s", "合计伤害"),
                (lambda item: [player["name"] for player in item.get("players", [])], "受伤人员"),
            ]),
        ],
    })

    consumables = report.get("consumables", {})
    death_aggregate = aggregate_rows(
        consumables.get("death_issues", []), ["player"], "missing"
    )
    sections.append({
        "title": "消耗品",
        "notes": [
            callout(
                "一分钟以上才计错",
                "常驻药剂只累计实际战斗中的缺失时间，纯脱战期间不计；缺失超过60秒才列。"
                "死亡造成效果消失时，检查下一次开怪前是否补回；下表按玩家和缺失药剂聚合。",
            ),
        ],
        "tables": [
            selected_table("到期后战斗内缺失超过60秒", consumables.get("expiration_issues", []), [
                ("player", "玩家"), ("name", "药剂"), ("expired", "失效时间"),
                ("regained", "补回时间"), ("combat_delay", "战斗内缺失（秒）"),
            ]),
            selected_table("死亡后下次开怪仍未补齐（聚合）", death_aggregate, [
                ("player", "玩家"), ("missing", "缺失药剂"), ("count", "次数"),
            ]),
            selected_table("指定恶魔首领开打时未吃屠魔药剂", consumables.get("demon_slaying_issues", []), [
                ("boss", "首领"), ("player", "玩家"), ("class", "职业"),
                ("boss_start", "开战时间"), ("regained", "补吃时间"),
            ]),
        ],
    })

    narmuun = bosses["守护者纳尔穆恩"]
    curse_summary = {}
    for item in narmuun.get("curse_issues", []):
        target = item.get("target")
        current = curse_summary.setdefault(target, {"target": target, "count": 0, "max_delay": 0, "damage": 0})
        current["count"] += 1
        current["max_delay"] = max(current["max_delay"], item.get("delay") or 0)
        current["damage"] += item.get("damage") or 0
    sections.append({
        "title": "守护者纳尔穆恩",
        "notes": [
            callout(
                "固定四项检查",
                "准备、红蓝月互伤、鲜血虹吸驱散、猫头鹰低血量攻击均保留。"
                "红蓝月按双向等额机制写成玩家对别人造成的伤害；超过1万才计错，主坦%s豁免。"
                "火炕检查排除全部坦克。" % (
                    bosses["守护者纳尔穆恩"].get("moon_exempt_main_tank") or "未识别"
                ),
            ),
            callout(
                "猫头鹰判定",
                "只统计四只全部死亡前10秒以外、猫头鹰已低于5%后的主动攻击；"
                "最后10秒、既有持续伤害和死亡太快没打到均不计。",
                "warning",
            ),
        ],
        "tables": [
            selected_table("1. 开打准备", narmuun.get("preparation", []), [
                ("item", "检查项"), ("log_aura", "日志效果"),
                ("missing", "缺失人员"), ("status", "结论"),
            ]),
            selected_table("2. 红月与蓝月互相伤害超过1万", [
                item for item in narmuun.get("moon_outgoing_by_player", []) if item.get("is_error")
            ], [
                ("player", "玩家"), ("assigned", "月色"), ("damaged_group", "伤害对象"),
                ("hits", "命中"), ("damage", "造成伤害"),
            ]),
            selected_table("3. 鲜血虹吸长时间未解除（按玩家汇总）", list(curse_summary.values()), [
                ("target", "玩家"), ("count", "次数"),
                ("max_delay", "最长持续（秒）"), ("damage", "累计伤害"),
            ]),
            selected_table("4. 猫头鹰低于5%后继续攻击", narmuun.get("owl_issues", []), [
                ("wave", "波次"), ("owl", "猫头鹰"), ("player", "玩家"),
                ("hits", "命中"), ("damage", "伤害"), ("death_offset", "该波结束"),
            ]),
            selected_table("解诅咒次数", narmuun.get("decurse_counts", []), [
                ("player", "玩家"), ("class", "职业"), ("count", "次数"),
            ]),
        ],
    })

    intagos = bosses["魔网观察者因塔苟斯"]
    affinity_rows = []
    for affinity in intagos.get("affinities", []):
        for player in affinity.get("players", []):
            row = dict(player)
            row.update({
                "attempt": "第%s次（%s）" % (affinity.get("attempt", 1), affinity.get("attempt_result", "击杀")),
                "affinity": affinity.get("affinity"),
                "school": affinity.get("allowed_school"),
                "window": "%s–%s" % (
                    format_offset(affinity.get("start_offset")),
                    format_offset(affinity.get("end_offset")),
                ),
                "outcome": affinity.get("outcome"),
            })
            affinity_rows.append(row)
    sections.append({
        "title": "魔网观察者因塔苟斯",
        "notes": [
            callout(
                "亲和对应属性",
                "红色=火焰、绿色=自然、水晶=物理、魔力=奥术、黑色=暗影、蓝色=冰霜。"
                "全部亲和及开打冰抗检查均排除坦克；火焰和冰霜不统计萨满，自然仍统计；"
                "若直接击杀首领或亲和爆炸后仍击杀，零伤害不计错。"
                "灭团尝试的亲和同样检查；团灭时亲和仍在、或亲和出现前已死亡的人不计错。"
                "亲和消失后15秒内首领单跳达到6000，视为亲和没打到0血（未打掉）。",
            ),
        ],
        "tables": [
            selected_table("1. 初始小怪未清先打首领", intagos.get("early_casters", []), [
                ("player", "玩家"), ("class", "职业"), ("first_offset", "首次攻击"),
                ("hits", "命中"), ("damage", "伤害"), (lambda item: spell_summary(item.get("spells")), "技能"),
            ]),
            selected_table("2. 亲和对应属性伤害", affinity_rows, [
                ("attempt", "尝试"), ("affinity", "亲和"), ("school", "只计属性"), ("window", "存在窗口"),
                ("player", "玩家"), ("class", "职业"), ("hits", "命中"),
                ("damage", "有效伤害"), ("result", "结论"),
            ]),
            selected_table("2.1 各次尝试亲和是否打掉", intagos.get("affinity_attempts", []), [
                ("attempt", "尝试"), ("attempt_result", "结果"), ("affinity", "亲和"),
                ("death_offset", "消失时间"), ("last_hit_gap", "最后一击距消失（秒）"),
                ("boss_hits", "消失后首领单跳（之前→之后）"), ("result", "结论"),
            ]),
            selected_table("3. 魔鳞诅咒长时间未解除", intagos.get("curse_results", []), [
                ("target", "玩家"), ("applied_offset", "中诅咒"), ("removed_offset", "解除"),
                ("delay", "持续（秒）"), ("status", "结论"),
            ], empty="本周没有长时间未解除记录"),
            selected_table("4. 开打时冰抗", intagos.get("preparation", []), [
                ("item", "检查项"), ("missing", "缺失人员"), ("status", "结论"),
            ]),
            selected_table("解诅咒次数", intagos.get("decurse_counts", []), [
                ("player", "玩家"), ("class", "职业"), ("count", "次数"),
            ]),
        ],
    })

    anom = bosses["阿诺玛鲁斯"]
    sections.append({
        "title": "阿诺玛鲁斯",
        "notes": [
            callout(
                "抗性与爆炸口径",
                "奥抗合计装备、野性印记/赐福、魔法抗性药水和种族被动；装备快照不完整且低于180时只显示核验下限。"
                "奥术超载只关联持有者死亡或效果消失前后1秒内对应的连续爆炸批次；"
                "该窗口没有其他超载触发者时整批归因，且仅在人均全团伤害达到1200以上时计错。"
                "前三个超载点名可继续攻击到效果剩余8秒，"
                "其余点名仍按获得效果3秒后不得继续攻击。",
            ),
        ],
        "tables": [
            selected_table("1. 开打时全员奥抗", anom.get("arcane_resistance", []), [
                ("player", "玩家"), ("display_total", "显示奥抗"), ("gear", "装备"),
                ("buff", "增益"), ("potion", "药剂"), ("racial", "种族"),
                ("verified", "是否核实"), ("detail", "说明"),
            ]),
            selected_table("2. 开打时未吃奥术防护", anom.get("arcane_protection_missing", []), [
                (lambda item: item, "玩家"),
            ]),
            selected_table("3. 奥术监牢驱散", anom.get("arcane_prisons", []), [
                ("target", "目标"), ("applied_offset", "获得"),
                ("removed_offset", "解除"), ("delay", "持续（秒）"),
                ("dispelled", "已驱散"), ("dispeller", "驱散者"),
            ]),
            selected_table("4. 奥术超载爆炸", anom.get("overloads", []), [
                ("player", "点名"), ("applied_offset", "获得"),
                ("duration", "持续"), ("raid_hit_count", "炸到人数"),
                ("raid_damage", "全团伤害"), ("average_raid_damage", "人均伤害"),
                (lambda item: bool(item.get("killed")), "是否炸死人"),
                ("killed_players", "炸死（受到伤害）"),
                ("counted_error", "是否计错"),
                (lambda item: "连锁，归" + item["chained_to"] if item.get("chained_to") else item["trigger"], "归因"),
                ("soaked", "是否踩圈"),
            ]),
            selected_table("4.1 被奥术超载炸死且伤害未超过4000", anom.get("overload_death_issues", []), [
                ("player", "玩家"), ("offset", "时间"), ("damage", "受到伤害"),
                ("holders", "爆炸来源（持有者）"),
            ]),
            selected_table("5. 中超载超过允许时间仍攻击首领", anom.get("continued_attack_issues", []), [
                ("player", "玩家"), ("target_order", "点名顺序"), ("applied_offset", "点名时间"),
                ("allowed_until_offset", "允许攻击至"), ("rule", "判定规则"),
                ("first_attack_offset", "首次攻击"), ("hits", "命中"),
                ("damage", "伤害"), (lambda item: spell_summary(item.get("spells")), "技能"),
            ]),
            selected_table("6. 爆炸后直接攻击首领、未踩圈", anom.get("no_soak_issues", []), [
                ("player", "玩家"), ("suppression_offset", "爆炸时间"),
                ("first_attack_offset", "返回攻击"), ("hits", "命中"), ("damage", "伤害"),
            ]),
        ],
    })

    medivh = bosses["麦迪文的回响"]
    medivh_curse = find_curse(report, "麦迪文的回响", "语言诅咒") or {}
    sections.append({
        "title": "麦迪文的回响",
        "notes": [
            callout(
                "语言诅咒",
                "本周覆盖率%s%%，断档%s秒，责任人%s；法术ID 11719，确认是最高级语言诅咒。"
                % (
                    compact(medivh_curse.get("targetable_uptime_pct")),
                    compact(medivh_curse.get("total_gap")),
                    compact(medivh_curse.get("responsible")),
                ),
                "warning",
            ),
            callout(
                "打断规则",
                "除冰霜新星与暗影箭外，其他技能不应打断；冰霜新星和暗影箭应在读条最后0.5秒内打断。"
                "日志没有保存轮换分工，未打断只能写责任人未记录。",
            ),
        ],
        "tables": [
            selected_table("1. 错误打断其他技能", medivh.get("wrong_interrupts", []), [
                ("spell", "被打断技能"), ("start_offset", "开读条"),
                ("interrupt_offset", "打断时间"), ("interrupter", "打断者"),
                ("interrupt_spell", "打断技能"),
            ]),
            selected_table("2. 冰霜新星、暗影箭未打断或过早打断", medivh.get("priority_interrupt_issues", []), [
                ("spell", "技能"), ("start_offset", "开读条"), ("status", "结论"),
                ("interrupter", "打断者"), ("elapsed", "读条经过"),
                ("expected", "负责人"),
            ]),
            selected_table("3. 麦迪文的灾祸驱散", medivh.get("doom_dispels", []), [
                ("target", "目标"), ("dispeller", "驱散者"), ("offset", "时间"),
            ]),
            selected_table("4. 腐化直接点名", medivh.get("corruption_boss_applications", []), [
                ("offset", "时间"), (lambda item: "、".join(item.get("targets") or []), "目标"),
            ]),
            selected_table("5. 腐化传播", medivh.get("corruption_transmissions", []), [
                ("offset", "时间"),
                (lambda item: "、".join(item.get("sources") or []), "传播候选"),
                (lambda item: "、".join(item.get("targets") or []), "新感染者"),
                (lambda item: "是" if item.get("unique_source") else "否（多个候选，不计错）", "是否计错"),
            ]),
            selected_table("6. 腐化被直接驱散", medivh.get("corruption_dispels", []), [
                ("offset", "时间"), ("target", "目标"), ("dispeller", "驱散者"),
            ]),
            selected_table("7. 非坦克攻击势不可挡的地狱火", medivh.get("infernal_issues", []), [
                ("player", "玩家"), ("first_offset", "首次攻击"), ("hits", "命中次数"),
                ("damage", "伤害"), (lambda item: spell_summary(item.get("spells")), "技能"),
            ]),
        ],
    })

    king = bosses["国王（国际象棋）"]
    sections.append({
        "title": "国王（国际象棋）",
        "notes": [
            callout(
                note("king_attempts_title", "本周共%d次尝试" % len(king.get("attempts", []))),
                note("king_attempts_text", "开场三类棋子按职责检查：干枯的主教由远程负责，"
                "另外两类由近战负责；坦克豁免，10秒内死亡的小怪不判未转火。"),
            ),
        ],
        "tables": [
            selected_table("尝试结果", king.get("attempts", []), [
                ("attempt", "尝试"), ("result", "结果"), ("start", "开始"), ("end", "结束"),
            ]),
            selected_table("1. 开场小怪转火", king.get("opening_add_checks", []), [
                ("target", "目标"), ("responsibility", "负责职责"),
                ("window_end_offset", "检查窗口结束"), ("window_end_reason", "结束原因"),
                ("result", "结论"), ("noncontributors", "未参与人员"),
            ]),
            selected_table("2. 死于国王之怒或黑水", king.get("mechanic_deaths", []), [
                ("player", "玩家"), ("mechanic", "机制"), ("ts", "时间"), ("damage", "致死伤害"),
            ]),
            selected_table("3. 黑暗屈从下跪不及时", king.get("late_bows", []), [
                ("player", "玩家"), ("applied_offset", "获得"),
                ("damage_offset", "受罚"), ("delay", "延迟"), ("died", "是否死亡"),
            ]),
            selected_table("4. 首次心控未及时自行解除", king.get("first_charm_issues", []), [
                ("player", "玩家"), ("offset", "获得"), ("duration", "持续"),
                ("resolution", "结论"),
            ]),
            selected_table("5. 解诅咒次数", king.get("decurse_counts", []), [
                ("player", "玩家"), ("class", "职业"), ("count", "次数"), ("targets", "目标"),
            ]),
        ],
    })

    sanf = bosses["桑夫·塔斯达尔"]
    sections.append({
        "title": "桑夫·塔斯达尔",
        "notes": [
            callout(
                note("sanf_wipe_title", "灭团原因"),
                note("sanf_wipe_text", "本周桑夫没有灭团。"),
                "danger",
            ),
            callout(
                "裂隙诅咒按裂隙回馈死亡追责",
                "只有玩家死于裂隙回馈时才追查裂隙诅咒：有对应驱散记录则责任归驱散者；"
                "没有驱散记录则责任归死者本人。单点裂隙纠缠持有者才能攻击德莱尼虚无行者，"
                "解除或在小怪存在时未攻击均计错。场上没有虚无行者则不计。"
                "接首领坦克%s不检查虚无行者。"
                % (sanf.get("boss_tank") or "未识别"),
                "warning",
            ),
            callout(
                "大怪变身责任",
                "德莱尼裂隙行者成功形成裂隙元素时，全体物理近战各计1次错误。",
                "danger",
            ),
            callout(
                "仇恨溢出只有致死才计错",
                "血量足够时可以硬吃；命中但没有死亡不算错误。" + (
                    "本周日志没有确认由仇恨溢出直接造成的死亡；"
                    if not any(item.get("direct_deaths") for item in sanf.get("overflowing_hatreds", []))
                    else "本周日志确认%d人直接死于仇恨溢出；" % sum(
                        len(item.get("direct_deaths") or []) for item in sanf.get("overflowing_hatreds", [])
                    )
                ) +
                "表内附近死亡只表示发生在施放附近，不能归因为该技能。"
                "12000左右的伤害来自裂隙回馈，是未受裂隙诅咒保护时的惩罚。",
            ),
        ],
        "tables": [
            selected_table("尝试结果", sanf.get("attempts", []), [
                ("attempt", "尝试"), ("result", "结果"), ("start", "开始"), ("end", "结束"),
            ]),
            selected_table("1. 裂隙回馈死亡责任", sanf.get("rift_feedback_death_issues", []), [
                ("feedback_offset", "回馈时间"), ("victim", "死者"),
                ("damage", "伤害"), ("responsible", "责任人"),
                ("dispeller", "驱散者"), ("dispel_spell", "驱散技能"),
                ("dispel_offset", "驱散时间"), ("reason", "计错原因"),
            ]),
            selected_table("2. 错误解除裂隙纠缠", sanf.get("wrong_dispels", []), [
                ("offset", "时间"), ("caster", "驱散者"), ("target", "目标"),
                ("removed", "移除效果"), ("reason", "计错原因"),
            ]),
            selected_table("3. 裂隙纠缠期间未攻击虚无行者", [
                item for item in sanf.get("entanglement_issues", []) if item.get("counted_error")
            ], [
                ("player", "玩家"), ("applied_offset", "点名时间"),
                ("window", "纠缠窗口"), ("add_window", "小怪窗口"), ("result", "结论"),
            ]),
            selected_table("4. 大怪成功变身", sanf.get("large_add_transformations", []), [
                ("attempt", "尝试"), ("cast_offset", "开始施法"),
                ("observed_offset", "变身确认"), ("result", "结果"),
                ("responsible", "计错近战"), ("error_rule", "计错规则"),
            ]),
            selected_table("5. 裂隙追踪者处理", sanf.get("tracker_waves", []), [
                ("wave", "波次"), ("first_offset", "出现"),
                ("death_offset", "死亡"), ("duration", "存活"), ("result", "结论"),
            ]),
            selected_table("6. 裂隙回馈", sanf.get("rift_feedbacks", []), [
                ("cast_offset", "施放"), ("logged_targets", "日志目标"),
                ("damaged_players", "受伤人员"), ("damage", "伤害"), ("deaths", "死亡"),
            ]),
            selected_table("7. 仇恨溢出（冲击波）", sanf.get("overflowing_hatreds", []), [
                ("cast_offset", "施放"), ("resolution", "结算"),
                ("deaths", "附近死亡（非直接归因）"),
                ("direct_deaths", "直接致死"), ("counted_error", "是否计错"),
            ]),
            selected_table("8. 失落暗影转火", sanf.get("shadow_waves", []), [
                ("wave", "波次"), ("first_offset", "出现"), ("death_offset", "死亡"),
                ("count", "数量"), ("timely", "及时"), ("delayed", "过晚"), ("missed", "未打"),
            ]),
        ],
    })

    rupturan = bosses["破碎者鲁普图兰"]
    sections.append({
        "title": "破碎者鲁普图兰",
        "notes": [
            callout(
                "两阶段口径",
                "一阶段从%s开始，二阶段从开打后%s开始。首领5%%血量按一阶段本体累计承伤95%%倒推。"
                % (rupturan.get("start"), format_offset(rupturan.get("phase_two_offset"))),
            ),
            callout(
                "远程职责",
                "二阶段活体碎块转火不检查术士和牧师，因为他们负责抽取恶魔之心法力；治疗同样不承担攻击责任。",
                "warning",
            ),
        ],
        "tables": [
            selected_table("1. 一阶段被摇摇欲坠炸死", rupturan.get("eruption_deaths", []), [
                ("player", "玩家"), ("offset", "时间"), ("damage", "致死伤害"),
            ]),
            selected_table("2. 5%以下仍有活体石块时继续攻击首领", rupturan.get("low_health_boss_issues", []), [
                ("player", "玩家"), ("first_offset", "首次攻击"),
                ("hits", "命中"), ("damage", "伤害"),
            ]),
            selected_table("3. 二阶段活体碎块击杀玩家", rupturan.get("living_fragment_kills", []), [
                ("victim", "死者"), ("offset", "时间"), ("damage", "死前3秒碎块伤害"),
                ("last_hit", "最后一击"), ("non_attackers", "未转火远程"),
            ]),
            selected_table("4. 恶魔之心抽蓝", rupturan.get("mana_drains", []), [
                ("player", "玩家"), ("class", "职业"), ("ticks", "跳数"),
                ("amount", "抽蓝量"), ("spells", "技能"),
            ]),
            selected_table("5. 术士 / 牧师未抽蓝", rupturan.get("mana_noncontributors", []), [
                ("player", "玩家"), ("class", "职业"),
            ]),
        ],
    })

    kruul = bosses["库鲁尔"]
    sections.append({
        "title": "库鲁尔",
        "notes": [
            callout(
                "三项固定检查",
                "冷漠打击达到7层及以上时，在本场四名轮换坦克中排除正在承受冷漠打击的两人，"
                "未接手的另外两名坦克各计1次；"
                "第一阶段按本体累计承伤50%倒推，坦克不统计对地狱火的伤害。"
                "大领主印记解除触发的高伤暗影新星每次均计错，不要求当场致死；"
                "普通低伤暗影新星不计。",
            ),
        ],
        "tables": [
            selected_table("1. 冷漠打击达到7层及以上", kruul.get("high_stack_incidents", []), [
                ("stack", "层数"), ("offset", "时间"), ("players", "中层人员"),
                ("active_tanks", "承受冷漠的两名坦克"), ("responsible_tanks", "未接手的两名坦克"),
                ("late_taunt_offset", "迟到嘲讽"), ("late_by", "迟到（秒）"),
            ]),
            selected_table("2. 大领主印记驱散伤害", kruul.get("mark_explosions", []), [
                ("ts", "时间"), ("caster", "驱散者"), ("target", "目标"),
                ("hit_players", "炸到人数"), ("raid_damage_075s", "合计伤害"),
                (lambda item: [player["name"] for player in item.get("players", [])], "受伤人员"),
            ]),
            selected_table("3. 第一阶段非坦克攻击虚空地狱火", kruul.get("infernal_issues", []), [
                ("player", "玩家"), ("first_offset", "首次攻击"),
                ("hits", "命中"), ("damage", "伤害"),
                (lambda item: spell_summary(item.get("spells")), "技能"),
            ]),
        ],
    })

    meph = bosses["孟菲斯托斯"]
    curse_dispel_aggregate = aggregate_rows(meph.get("curse_dispels", []), ["aura", "dispeller"])
    crawler_errors = [
        item for item in meph.get("crawler_waves", [])
        if item.get("mana_drain_counts_as_error")
    ]
    eye = meph.get("eye_duty") or {}
    sections.append({
        "title": "孟菲斯托斯",
        "notes": [
            callout(
                "技能与解除规则",
                "外域的末日、无眠苦痛可以解除；不能提前解除的是军团镣铐，它不是诅咒。"
                + note("mephistroth_shackles", ""),
            ),
            callout(
                "恶魔之眼职责豁免",
                "引眼：%s；陪同驱散：%s。两人不纳入噩梦爬行者转火检查。"
                "爬行者只有开始无尽饥渴且实际吸到法力才计错；首领30%%以下豁免。"
                "首领55%%至下一次水晶的停手检查排除坦克。"
                % (eye.get("bait") or "未识别", eye.get("dispeller") or "未识别"),
                "warning",
            ),
        ],
        "tables": [
            selected_table("1. 可解除诅咒的驱散统计", curse_dispel_aggregate, [
                ("aura", "效果"), ("dispeller", "驱散者"), ("count", "次数"),
            ]),
            selected_table("2. 外域的末日结算", meph.get("doom_applications", []), [
                ("target", "目标"), ("applied_offset", "获得"),
                ("duration", "持续"), ("resolution", "结算"),
            ]),
            selected_table("3. 军团镣铐异常挣脱", meph.get("shackle_explosions", []), [
                ("attempt", "尝试"), ("trigger", "触发者"), ("offset", "时间"),
                ("hits", "炸到人数"), ("damage", "伤害"),
                (lambda item: "连锁，归%s" % item["chained_to"] if item.get("chained_to") else "本人", "归因"),
                ("players", "受伤人员"),
            ]),
            selected_table("4. 噩梦爬行者吸蓝前未转火", crawler_errors, [
                ("wave", "波次"), ("spawn_offset", "生成"),
                ("mana_drain_hit_offset", "吸蓝命中"), ("duration", "存活"),
                ("ranged_noncontributors", "未转火远程"),
                (lambda item: [player["player"] for player in item.get("ranged_contributors", [])], "参与转火"),
            ]),
            selected_table("5. 首领55%至下一次水晶期间继续攻击", meph.get("forbidden_boss_attacks", []), [
                ("player", "玩家"), ("first_offset", "首次攻击"),
                ("hits", "命中"), ("damage", "伤害"),
                (lambda item: spell_summary(item.get("spells")), "技能"),
            ]),
            selected_table("6. 地狱之怒碎片（水晶）", meph.get("crystal_waves", []), [
                ("wave", "轮次"), ("cast_offset", "施放"),
                ("deaths", "击杀碎片数"), ("last_death_offset", "最后击杀"),
                ("result", "结论"),
            ]),
        ],
    })

    return {
        "title": "卡塔赞之塔战斗审计 · 单页版",
        "subtitle": "%s · 开团时间 %s" % (metadata["date"], metadata["raid_start"]),
        "date": metadata["date"],
        "stats": stats,
        "sections": sections,
    }


def render_canvas(model):
    data = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    return r'''import {
  Callout, Card, CardBody, CardHeader, Grid, H1, H2, Row, Stack,
  Stat, Table, Text, useHostTheme,
} from "cursor/canvas";

const report = __DATA__;

function ReportSection({ section }) {
  return (
    <Stack gap={14}>
      <H1>{section.title}</H1>
      {section.notes.map((note, index) => (
        <Callout
          key={index}
          tone={typeof note === "string" ? "info" : note.tone}
          title={typeof note === "string" ? (index === 0 ? "本周结论" : "说明") : note.title}
        >
          {typeof note === "string" ? note : note.text}
        </Callout>
      ))}
      {section.tables.map((table, index) => (
        <Stack key={index} gap={8}>
          <H2>{table.title}</H2>
          <Table headers={table.headers} rows={table.rows} striped stickyHeader />
        </Stack>
      ))}
    </Stack>
  );
}

export default function KarazhanReport() {
  const theme = useHostTheme();
  return (
    <Stack gap={24} style={{ padding: 24, background: theme.bg.editor, color: theme.text.primary, minHeight: "100vh" }}>
      <Stack gap={6}>
        <H1>{report.title}</H1>
        <Text tone="secondary">{report.subtitle}</Text>
      </Stack>
      <Grid columns="repeat(4, minmax(0, 1fr))" gap={12}>
        {report.stats.map((item) => (
          <Card key={item[0]}><CardHeader>{item[0]}</CardHeader><CardBody><Stat value={String(item[1])} /></CardBody></Card>
        ))}
      </Grid>
      {report.sections.map((section) => <ReportSection key={section.title} section={section} />)}
    </Stack>
  );
}
'''.replace("__DATA__", data)


HTML_STYLE = r"""
:root{color-scheme:dark;--bg:#0b1015;--panel:#141b22;--panel2:#18232d;--ink:#edf1f3;--muted:#9daab3;--gold:#d8b46a;--line:#31404b;--danger:#ef7777}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 15% 0,#173342 0,transparent 32rem),var(--bg);color:var(--ink);font:15px/1.65 "Microsoft YaHei UI","Noto Sans SC",sans-serif}
.site-nav{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;padding:12px max(18px,calc((100vw - 1500px)/2));background:#0b1015e8;border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}
.site-nav a{color:var(--gold);text-decoration:none}main{width:min(1500px,calc(100% - 32px));margin:auto;padding:46px 0 90px}
header{padding:30px 0 38px;border-bottom:1px solid var(--line)}h1{margin:.2em 0;font-size:clamp(30px,5vw,58px);line-height:1.1}h2{margin:48px 0 14px;color:var(--gold);font-size:26px}h3{margin:28px 0 10px;font-size:18px}
.subtitle,.muted{color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:24px}.stat{padding:16px;border:1px solid var(--line);background:var(--panel)}.stat b{display:block;color:var(--gold);font-size:20px}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0}.toc a{padding:6px 10px;border:1px solid var(--line);color:var(--ink);text-decoration:none;background:var(--panel)}
section{scroll-margin-top:62px}.note{margin:9px 0;padding:12px 14px;border-left:3px solid var(--gold);background:var(--panel2);overflow-wrap:anywhere}.note strong{display:block;margin-bottom:3px;color:var(--gold)}.note.warning{border-left-color:#e8a94f;background:#2a2117}.note.danger{border-left-color:var(--danger);background:#2b181b}.note.danger strong{color:#ff9b9b}
.table-wrap{overflow:auto;border:1px solid var(--line);background:var(--panel)}table{width:100%;border-collapse:collapse;min-width:720px}th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere;word-break:break-word}th{position:sticky;top:0;background:#1b2731;color:var(--gold);white-space:nowrap}tr:nth-child(even) td{background:#111920}
@media(max-width:700px){
  .site-nav{padding:10px 12px}.site-nav span{display:none}
  main{width:100%;padding:18px 12px 64px}header{padding:20px 0 26px}
  h1{font-size:30px}h2{margin-top:38px;font-size:23px}h3{font-size:17px}
  .stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.stat{min-width:0;padding:12px}.stat b{font-size:17px;overflow-wrap:anywhere}
  .toc{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.toc a{display:flex;align-items:center;min-width:0;padding:7px 8px;line-height:1.35}
  .note{padding:11px 12px}
  .table-wrap{overflow:visible;border:0;background:transparent}
  table{min-width:0;border-collapse:separate;border-spacing:0 9px}
  thead{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
  tbody,tr,td{display:block;width:100%}
  tr{border:1px solid var(--line);background:var(--panel);box-shadow:0 7px 18px #0003}
  td, tr:nth-child(even) td{display:grid;grid-template-columns:minmax(88px,34%) minmax(0,1fr);gap:10px;padding:7px 10px;border:0;background:transparent}
  td:first-child{padding-top:11px}td:last-child{padding-bottom:11px}
  td::before{content:attr(data-label);color:var(--gold);font-weight:700;overflow-wrap:anywhere}
}
"""


def render_html(model):
    toc = "\n".join(
        '<a href="#section-%d">%s</a>' % (index, escape(section["title"]))
        for index, section in enumerate(model["sections"], 1)
    )
    stats = "\n".join(
        '<div class="stat"><span>%s</span><b>%s</b></div>' % (
            escape(str(label)), escape(str(value))
        ) for label, value in model["stats"]
    )
    section_html = []
    for index, section in enumerate(model["sections"], 1):
        parts = ['<section id="section-%d"><h2>%s</h2>' % (index, escape(section["title"]))]
        for note in section["notes"]:
            if isinstance(note, dict):
                parts.append(
                    '<aside class="note %s"><strong>%s</strong>%s</aside>' % (
                        escape(str(note.get("tone", "info"))),
                        escape(str(note.get("title", "说明"))),
                        escape(str(note.get("text", ""))),
                    )
                )
            else:
                parts.append('<div class="note">%s</div>' % escape(str(note)))
        for table in section["tables"]:
            parts.append("<h3>%s</h3>" % escape(table["title"]))
            parts.append('<div class="table-wrap"><table><thead><tr>')
            parts.extend("<th>%s</th>" % escape(str(header)) for header in table["headers"])
            parts.append("</tr></thead><tbody>")
            for row in table["rows"]:
                parts.append("<tr>")
                parts.extend(
                    '<td data-label="%s">%s</td>' % (
                        escape(str(table["headers"][cell_index])),
                        escape(str(cell)),
                    )
                    for cell_index, cell in enumerate(row)
                )
                parts.append("</tr>")
            parts.append("</tbody></table></div>")
        parts.append("</section>")
        section_html.append("\n".join(parts))
    return u"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{title} {date}"><title>{title} · {date}</title><style>{style}</style></head>
<body><nav class="site-nav" aria-label="站点导航"><a href="../../">← 返回日期列表</a><span>卡塔赞战斗档案</span></nav>
<main><header><div class="muted">团队战斗日志审计</div><h1>{title}</h1><div class="subtitle">{subtitle}</div>
<div class="stats">{stats}</div></header><nav class="toc" aria-label="报告目录">{toc}</nav>{sections}</main></body></html>
""".format(
        title=escape(model["title"]), date=escape(model["date"]),
        subtitle=escape(model["subtitle"]), style=HTML_STYLE,
        stats=stats, toc=toc, sections="\n".join(section_html),
    )
