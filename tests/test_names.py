"""姓名歧义。夹具姓名是合成的，不使用当周玩家。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from karazhan_tool.model import Player
from karazhan_tool.parser.names import FrozenRoster, resolve_source_prefix, resolve_unit_name


def make_player(guid: str, name: str, class_id: str = "WARRIOR") -> Player:
    return Player(guid, name, class_id, class_id, ("test",), True)


def make_roster(*extra: Player, logger_name: str = "记录者", logger_guid: str = "0x10") -> FrozenRoster:
    logger = make_player(logger_guid, logger_name, "DRUID")
    return FrozenRoster((logger, *extra), logger)


class NameResolutionTest(unittest.TestCase):
    def test_you_maps_to_logger_when_nobody_uses_that_name(self) -> None:
        roster = make_roster(make_player("0x2", "张三"))
        result = resolve_source_prefix("你", roster)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.method, "logger_pronoun")
        self.assertEqual(result.name, "记录者")
        self.assertIsNone(result.spell)

    def test_your_spell_maps_to_logger(self) -> None:
        roster = make_roster(make_player("0x2", "张三"))
        result = resolve_source_prefix("你的寒冰箭", roster)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.name, "记录者")
        self.assertEqual(result.spell, "寒冰箭")
        self.assertEqual(result.method, "logger_pronoun")

    def test_player_named_your_frostbolt_stays_ambiguous(self) -> None:
        roster = make_roster(make_player("0x2", "你的寒冰箭"))
        original = roster.players_named("你的寒冰箭")[0].name
        result = resolve_source_prefix("你的寒冰箭", roster)
        self.assertEqual(original, "你的寒冰箭")
        self.assertEqual(result.status, "ambiguous")
        self.assertIn("ambiguous_name", result.flags)
        self.assertEqual(result.confidence, "low")
        readings = {(item.name, item.spell) for item in result.candidates}
        self.assertEqual(readings, {("你的寒冰箭", None), ("记录者", "寒冰箭")})

    def test_player_named_you_conflicts_with_logger_spell(self) -> None:
        roster = make_roster(make_player("0x2", "你"))
        result = resolve_source_prefix("你的寒冰箭", roster)
        self.assertEqual(result.status, "ambiguous")
        readings = {(item.name, item.spell) for item in result.candidates}
        self.assertEqual(readings, {("你", "寒冰箭"), ("记录者", "寒冰箭")})

    def test_player_named_yours_is_not_replaced(self) -> None:
        roster = make_roster(make_player("0x2", "你的"))
        result = resolve_source_prefix("你的", roster)
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.name, "你的")
        self.assertEqual(result.method, "longest_name")
        self.assertIsNone(result.spell)
        spell = resolve_source_prefix("你的寒冰箭", roster)
        self.assertEqual(spell.name, "记录者")
        self.assertEqual(spell.spell, "寒冰箭")

    def test_logger_whose_name_is_a_spell_phrase_stays_ambiguous(self) -> None:
        roster = make_roster(logger_name="你的寒冰箭", logger_guid="0x10")
        result = resolve_source_prefix("你的寒冰箭", roster)
        self.assertEqual(result.status, "ambiguous")
        readings = {(item.name, item.spell) for item in result.candidates}
        self.assertEqual(readings, {("你的寒冰箭", None), ("你的寒冰箭", "寒冰箭")})

    def test_longest_name_beats_prefix(self) -> None:
        roster = make_roster(make_player("0x2", "张三"), make_player("0x3", "张三丰"))
        melee = resolve_source_prefix("张三丰", roster)
        self.assertEqual((melee.name, melee.spell, melee.method), ("张三丰", None, "longest_name"))
        cast = resolve_source_prefix("张三丰的火球术", roster)
        self.assertEqual((cast.name, cast.spell), ("张三丰", "火球术"))
        short = resolve_source_prefix("张三的火球术", roster)
        self.assertEqual((short.name, short.spell), ("张三", "火球术"))
        decorated = resolve_source_prefix("张三的火球术(强化)", roster)
        self.assertEqual((decorated.name, decorated.spell), ("张三", "火球术(强化)"))

    def test_duplicate_names_without_guid_are_ambiguous(self) -> None:
        roster = make_roster(make_player("0x2", "张三"), make_player("0x3", "张三"))
        result = resolve_source_prefix("张三的火球术", roster)
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual({item.guid for item in result.candidates}, {"0x2", "0x3"})

    def test_guid_selects_logger_spell_over_same_text_player(self) -> None:
        roster = make_roster(make_player("0x2", "你的寒冰箭"))
        result = resolve_source_prefix("你的寒冰箭", roster, guid="0x10")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.method, "guid")
        self.assertEqual(result.name, "记录者")
        self.assertEqual(result.spell, "寒冰箭")
        self.assertNotIn("ambiguous_name", result.flags)

    def test_guid_selects_the_player_whose_name_looks_like_a_spell(self) -> None:
        roster = make_roster(make_player("0x2", "你的寒冰箭"))
        result = resolve_source_prefix("你的寒冰箭", roster, guid="0X2")
        self.assertEqual(result.method, "guid")
        self.assertEqual(result.name, "你的寒冰箭")
        self.assertIsNone(result.spell)
        self.assertEqual(result.confidence, "high")

    def test_unknown_guid_is_not_guessed_from_text(self) -> None:
        roster = make_roster()
        result = resolve_source_prefix("你的寒冰箭", roster, guid="0x999")
        self.assertEqual(result.status, "unresolved")
        self.assertIn("unknown_guid", result.flags)
        self.assertIsNone(result.name)

    def test_guid_text_mismatch_does_not_borrow_another_spell(self) -> None:
        roster = make_roster(make_player("0x2", "张三"))
        result = resolve_source_prefix("你的寒冰箭", roster, guid="0x2")
        self.assertEqual(result.name, "张三")
        self.assertIsNone(result.spell)
        self.assertIn("guid_text_mismatch", result.flags)
        self.assertEqual(result.confidence, "medium")

    def test_unit_pronoun_and_real_name(self) -> None:
        plain = resolve_unit_name("你", make_roster())
        self.assertEqual(plain.name, "记录者")
        self.assertEqual(resolve_unit_name("你自己", make_roster()).name, "记录者")
        conflict = resolve_unit_name("你", make_roster(make_player("0x2", "你")))
        self.assertEqual(conflict.status, "ambiguous")
        named = resolve_unit_name("你的寒冰箭", make_roster(make_player("0x2", "你的寒冰箭")))
        self.assertEqual(named.status, "resolved")
        self.assertEqual(named.name, "你的寒冰箭")
        missing = resolve_unit_name("你的寒冰箭", make_roster())
        self.assertEqual(missing.status, "unresolved")
        self.assertIsNone(missing.name)

    def test_npc_name_containing_de_is_not_split(self) -> None:
        result = resolve_source_prefix("苍白的骑兵", make_roster(make_player("0x2", "张三")))
        self.assertEqual(result.status, "unresolved")
        self.assertIsNone(result.name)

    def test_pet_owner_and_ambiguous_owner(self) -> None:
        roster = make_roster(make_player("0x2", "张三"))
        result = resolve_source_prefix("小狼 (张三)的撕咬", roster)
        self.assertEqual(result.method, "pet_owner")
        self.assertEqual(result.name, "张三")
        self.assertEqual(result.spell, "撕咬")
        self.assertEqual(result.pet, "小狼")
        yours = resolve_source_prefix("小狼(你)的爪击", roster)
        self.assertEqual(yours.name, "记录者")
        self.assertEqual(yours.spell, "爪击")
        conflict = make_roster(make_player("0x2", "你"))
        ambiguous = resolve_source_prefix("小狼 (你)", conflict)
        self.assertEqual(ambiguous.status, "ambiguous")

    def test_missing_logger_does_not_silently_pick_namesake(self) -> None:
        player = make_player("0x2", "你")
        roster = FrozenRoster((player,), None)
        result = resolve_unit_name("你", roster)
        self.assertEqual(result.status, "ambiguous")
        self.assertIn("missing_logger_identity", result.flags)

    def test_same_guid_cannot_change_display_name(self) -> None:
        with self.assertRaises(ValueError):
            FrozenRoster(
                (make_player("0x2", "张三"), make_player("0x2", "张三丰")),
                None,
            )


if __name__ == "__main__":
    unittest.main()
