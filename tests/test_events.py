"""关键日志事件。夹具姓名是合成的。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from karazhan_tool.model import Player
from karazhan_tool.parser.events import iter_events, parse_body
from karazhan_tool.parser.evidence import read_lines
from karazhan_tool.parser.names import FrozenRoster

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "events" / "combat.txt"


def roster_with(*extra: Player) -> FrozenRoster:
    logger = Player("0x10", "记录者", "DRUID", "德鲁伊", ("test",), True)
    players = (
        logger,
        Player("0x2", "张三", "MAGE", "法师", ("test",), True),
        Player("0x3", "张三丰", "MAGE", "法师", ("test",), True),
        *extra,
    )
    return FrozenRoster(players, logger)


class EventParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roster = roster_with()
        self.units = ("孟菲斯托斯", "苍白的骑兵")

    def test_window_keeps_raid_lines_only(self) -> None:
        events = list(
            iter_events(
                FIXTURE,
                self.roster,
                date="2026-11-18",
                start="19:00:00.000",
                end="19:10:00.000",
                known_units=self.units,
            )
        )
        self.assertEqual(len(events), 15)
        self.assertTrue(all(event.type != "UNPARSED" for event in events))
        self.assertEqual(events[0].seconds, 19 * 3600)

    def test_pronoun_spell_is_not_a_player_name(self) -> None:
        event = parse_body("你的寒冰箭击中训练假人造成120点冰霜伤害。", self.roster)
        self.assertEqual(event.type, "DAMAGE")
        self.assertEqual(event.source, "记录者")
        self.assertEqual(event.source_guid, "0x10")
        self.assertEqual(event.source_resolution, "logger_pronoun")
        self.assertEqual(event.spell, "寒冰箭")
        self.assertEqual(event.school, "冰霜")
        self.assertEqual(event.amount, 120)
        self.assertNotIn("text", event.to_dict())

    def test_real_player_named_like_a_spell_stays_ambiguous(self) -> None:
        roster = roster_with(Player("0x9", "你的寒冰箭", "MAGE", "法师", ("test",), True))
        event = parse_body("你的寒冰箭击中训练假人造成120点冰霜伤害。", roster)
        self.assertIn("ambiguous_name", event.flags)
        self.assertIsNone(event.source)
        names = {item["name"] for item in event.candidates}
        self.assertEqual(names, {"你的寒冰箭", "记录者"})

    def test_longest_name_damage_crit_and_partial_resist(self) -> None:
        resisted = parse_body(
            "张三丰的火球术击中训练假人造成30点火焰伤害。（10点被抵抗）",
            self.roster,
        )
        self.assertEqual(resisted.source, "张三丰")
        self.assertEqual(resisted.source_guid, "0x3")
        self.assertEqual(resisted.spell, "火球术")
        self.assertEqual(resisted.resisted, 10)
        crit = parse_body("张三的火球术致命一击对训练假人造成80点火焰伤害。", self.roster)
        self.assertEqual(crit.source, "张三")
        self.assertTrue(crit.critical)
        self.assertEqual(crit.amount, 80)

    def test_aura_death_heal_and_fail(self) -> None:
        gain = parse_body("张三获得了奥术智慧的效果（1）。", self.roster)
        self.assertEqual((gain.type, gain.target, gain.spell, gain.stacks), ("AURA_GAIN", "张三", "奥术智慧", 1))
        fade = parse_body("奥术智慧效果从你身上消失。", self.roster)
        self.assertEqual((fade.type, fade.target, fade.spell), ("AURA_FADE", "记录者", "奥术智慧"))
        faded = parse_body("恢复效果从你身上消失了。", self.roster)
        self.assertEqual((faded.type, faded.target), ("AURA_FADE", "记录者"))
        taunt = parse_body("张三对训练假人使用嘲讽。", self.roster)
        self.assertEqual((taunt.type, taunt.source, taunt.spell), ("CAST_SUCCESS", "张三", "嘲讽"))
        whiff = parse_body("张三没有击中训练假人。", self.roster)
        self.assertEqual((whiff.type, whiff.miss), ("MISS", "未命中"))
        caused = parse_body("你因张三的愈合而获得了40点生命值。", self.roster)
        self.assertEqual((caused.type, caused.source, caused.target, caused.spell, caused.amount), ("HEAL", "张三", "记录者", "愈合", 40))
        aura_hit = parse_body("你受到20点暗影伤害（训练假人的苦痛光环）。", self.roster)
        self.assertEqual((aura_hit.type, aura_hit.target, aura_hit.spell, aura_hit.amount), ("DAMAGE", "记录者", "苦痛光环", 20))
        death = parse_body("张三死亡了。", self.roster)
        self.assertEqual((death.type, death.target_guid), ("DEATH", "0x2"))
        heal = parse_body("记录者的治疗术为张三恢复了50点生命值。", self.roster)
        self.assertEqual((heal.type, heal.source, heal.target, heal.spell, heal.amount), ("HEAL", "记录者", "张三", "治疗术", 50))
        hot = parse_body("张三获得40点生命值（记录者的回春术）。", self.roster)
        self.assertEqual((hot.source, hot.spell, hot.amount), ("记录者", "回春术", 40))
        failed = parse_body("你施放星火术失败：被打断", self.roster)
        self.assertEqual((failed.type, failed.source, failed.spell, failed.miss), ("CAST_FAIL", "记录者", "星火术", "被打断"))

    def test_interrupt_resist_parry_boss_and_known_npc(self) -> None:
        interrupted = parse_body("张三丰打断了训练假人的火球术。", self.roster)
        self.assertEqual((interrupted.type, interrupted.source, interrupted.target, interrupted.spell), ("INTERRUPT", "张三丰", "训练假人", "火球术"))
        miss = parse_body("张三的火舌攻击被训练假人抵抗了。", self.roster)
        self.assertEqual((miss.type, miss.source, miss.spell, miss.miss), ("MISS", "张三", "火舌攻击", "抵抗"))
        parry = parse_body("训练假人发起了攻击。张三招架住了。", self.roster)
        self.assertEqual((parry.type, parry.source, parry.target, parry.miss), ("MISS", "训练假人", "张三", "招架"))
        dot = parse_body("孟菲斯托斯的腐臭虫群使张三受到了15点自然伤害。", self.roster, known_units=self.units)
        self.assertEqual((dot.source, dot.spell, dot.amount, dot.school), ("孟菲斯托斯", "腐臭虫群", 15, "自然"))
        npc = parse_body("苍白的骑兵击中张三造成5点伤害。", self.roster, known_units=self.units)
        self.assertEqual((npc.source, npc.spell, npc.target), ("苍白的骑兵", "近战", "张三"))
        removed = parse_body("张三的奥术智慧被记录者移除了。", self.roster)
        self.assertEqual((removed.type, removed.source, removed.target, removed.spell), ("AURA_REMOVED", "记录者", "张三", "奥术智慧"))

    def test_evidence_reads_only_the_requested_lines(self) -> None:
        rows = read_lines(FIXTURE, 2, before=1, after=0)
        self.assertEqual([row["line"] for row in rows], [1, 2])
        self.assertTrue(rows[1]["focus"])
        self.assertIn("寒冰箭", rows[1]["text"])


if __name__ == "__main__":
    unittest.main()
