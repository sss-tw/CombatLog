"""名单冻结与时间。夹具不使用当周玩家。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from karazhan_tool.config import load_config
from karazhan_tool.hashing import canonical_sha256
from karazhan_tool.parser.roster import InputCoverageError, freeze_roster
from karazhan_tool.timeutil import clock_to_epoch_ms, epoch_ms_to_local, parse_clock

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "roster"


class TimeTest(unittest.TestCase):
    def test_known_custom_data_anchor(self) -> None:
        self.assertEqual(clock_to_epoch_ms("2026-11-18", "19:49:06.458", "+08:00"), 1795002546458)
        self.assertEqual(epoch_ms_to_local(1795002546458, "+08:00"), ("2026-11-18", "19:49:06.458"))

    def test_raid_start_seconds(self) -> None:
        self.assertEqual(parse_clock("19:24:07.050"), 69847.050)

    def test_rejects_incomplete_clock(self) -> None:
        with self.assertRaises(ValueError):
            parse_clock("19:24:07")
        with self.assertRaises(ValueError):
            parse_clock("25:00:00.000")


class RosterFreezeTest(unittest.TestCase):
    def test_config_uses_relative_fixture_paths(self) -> None:
        config = load_config(FIXTURE / "config.json")
        self.assertEqual(config.custom_data, (FIXTURE / "custom_basic.txt").resolve())
        self.assertEqual(config.logger_name, "记录者")

    def test_participation_window_excludes_early_visitor(self) -> None:
        result = freeze_roster(
            custom_data=FIXTURE / "custom_basic.txt",
            raw_combat_log=FIXTURE / "raw_basic.txt",
            date="2026-11-18",
            timezone="+08:00",
            raid_start="19:00:00.000",
            raid_end="19:10:00.000",
            zone_names=("测试副本",),
            logger_guid="0x0000000000000004",
            logger_name="记录者",
        )
        names = [player.name for player in result.roster.players]
        self.assertEqual(names, ["张三", "张三丰", "记录者"])
        self.assertNotIn("路过", names)
        zhang = result.roster.players_named("张三")[0]
        self.assertEqual(zhang.class_name, "战士")
        self.assertEqual(zhang.guid, "0x0000000000000002")
        self.assertEqual(result.roster.logger.name, "记录者")
        self.assertEqual(result.warnings, ())

    def test_logger_is_kept_when_raw_log_uses_pronoun(self) -> None:
        result = freeze_roster(
            custom_data=FIXTURE / "custom_basic.txt",
            raw_combat_log=FIXTURE / "raw_pronoun.txt",
            date="2026-11-18",
            timezone="+08:00",
            raid_start="19:00:00.000",
            raid_end="19:10:00.000",
            zone_names=("测试副本",),
            logger_guid="0x0000000000000004",
            logger_name="记录者",
        )
        self.assertEqual([player.name for player in result.roster.players], ["张三", "张三丰", "记录者"])
        self.assertEqual(result.roster.logger.guid, "0x0000000000000004")
        self.assertEqual(result.warnings, ())

    def test_latest_name_inside_window_is_frozen(self) -> None:
        result = freeze_roster(
            custom_data=FIXTURE / "custom_rename.txt",
            raw_combat_log=FIXTURE / "raw_basic.txt",
            date="2026-11-18",
            timezone="+08:00",
            raid_start="19:00:00.000",
            raid_end="19:10:00.000",
            zone_names=("测试副本",),
            logger_guid="0x0000000000000004",
            logger_name="记录者",
        )
        self.assertIn("张老三", [player.name for player in result.roster.players])
        self.assertFalse(result.roster.players_named("张三"))
        self.assertTrue(any("张老三" in warning and "张三" in warning for warning in result.warnings))
        self.assertEqual(result.roster.by_guid["0x0000000000000002"].name, "张老三")

    def test_exclude_override_removes_a_participant(self) -> None:
        result = freeze_roster(
            custom_data=FIXTURE / "custom_basic.txt",
            raw_combat_log=FIXTURE / "raw_basic.txt",
            date="2026-11-18",
            timezone="+08:00",
            raid_start="19:00:00.000",
            raid_end="19:10:00.000",
            zone_names=("测试副本",),
            logger_guid="0x0000000000000004",
            logger_name="记录者",
            roster_overrides=({"action": "exclude", "name": "张三丰"},),
        )
        self.assertEqual([player.name for player in result.roster.players], ["张三", "记录者"])

    def test_player_absent_from_every_encounter_is_dropped(self) -> None:
        result = freeze_roster(
            custom_data=FIXTURE / "custom_basic.txt",
            raw_combat_log=FIXTURE / "raw_basic.txt",
            date="2026-11-18",
            timezone="+08:00",
            raid_start="19:00:00.000",
            raid_end="19:10:00.000",
            zone_names=("测试副本",),
            logger_guid="0x0000000000000004",
            logger_name="记录者",
            encounter_windows=(("19:02:00.000", "19:05:00.000"),),
        )
        names = [player.name for player in result.roster.players]
        self.assertEqual(names, ["张三丰", "记录者"])
        self.assertTrue(any("张三" in warning and "首领战" in warning for warning in result.warnings))

    def test_custom_data_outside_the_raid_is_rejected(self) -> None:
        with self.assertRaises(InputCoverageError):
            freeze_roster(
                custom_data=FIXTURE / "custom_outside.txt",
                raw_combat_log=FIXTURE / "raw_basic.txt",
                date="2026-11-18",
                timezone="+08:00",
                raid_start="19:00:00.000",
                raid_end="19:10:00.000",
                zone_names=("测试副本",),
                logger_guid="0x0000000000000004",
                logger_name="记录者",
            )

    def test_config_requires_logger_identity(self) -> None:
        payload = json.loads((FIXTURE / "config.json").read_text(encoding="utf-8"))
        payload.pop("logger_identity")
        broken = FIXTURE / "config_missing.json"
        broken.write_text(json.dumps(payload), encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                load_config(broken)
        finally:
            broken.unlink(missing_ok=True)


class HashTest(unittest.TestCase):
    def test_canonical_hash_ignores_key_order(self) -> None:
        self.assertEqual(canonical_sha256({"b": 1, "a": 2}), canonical_sha256({"a": 2, "b": 1}))


class SourceGuardTest(unittest.TestCase):
    def test_generic_code_has_no_weekly_player_names(self) -> None:
        golden = json.loads((ROOT / "tests" / "golden" / "2026-11-18" / "metrics.json").read_text(encoding="utf-8"))
        banned = tuple(golden["roster"]) + ("你的寒冰箭",)
        root = ROOT / "src"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in banned:
                self.assertNotIn(name, text, f"{path} 写死了 {name}")


if __name__ == "__main__":
    unittest.main()
