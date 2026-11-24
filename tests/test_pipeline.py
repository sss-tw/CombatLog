"""规则引擎姓名处理、证据、校验与发布门禁。夹具不使用当周玩家。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from karazhan_tool.analyze import attach_evidence, normalize_unordered
from karazhan_tool.compare import summarize_diff
from karazhan_tool.hashing import sha256_file
from karazhan_tool.rules import engine
from karazhan_tool.site import add_home_card, check_gate
from karazhan_tool.validate import validate


def configure(players: dict[str, str], logger: str = "记录者") -> None:
    engine.configure({
        "date": "2026-11-18",
        "date_prefix": "11/18 ",
        "combat_log": "unused.txt",
        "gear_snapshot_file": "unused.txt",
        "custom_data_files": [],
        "anchor_epoch_ms": 0,
        "anchor_log_time": "19:00:00.000",
        "logger_name": logger,
        "prep_start": None,
        "encounters": [("训练首领", "19:00:00.000", "19:05:00.000")],
        "extra_boss_windows": [],
        "attempts": {},
        "demon_slaying_bosses": [],
        "wipe_causes": [],
        "known_units": ["苍白的骑兵"],
        "raid_start": "19:00:00.000",
        "raid_end": "19:10:00.000",
        "player_classes": players,
    })


class EngineNameTest(unittest.TestCase):
    def test_pronoun_maps_to_logger_without_namesake(self) -> None:
        configure({"张三": "法师", "记录者": "德鲁伊"})
        roster = {"张三", "记录者"}
        self.assertEqual(engine.split_source("你的寒冰箭", roster), ("记录者", "寒冰箭"))
        self.assertEqual(engine.split_source("你", roster), ("记录者", "近战"))
        self.assertEqual(engine.normalize_unit("你"), "记录者")
        self.assertEqual(engine.NAME_ISSUES, [])

    def test_player_named_like_possessive_stays_and_is_flagged(self) -> None:
        configure({"你的寒冰箭": "法师", "记录者": "德鲁伊"})
        roster = {"你的寒冰箭", "记录者"}
        self.assertEqual(engine.split_source("你的寒冰箭", roster), ("你的寒冰箭", "近战"))
        self.assertEqual(engine.NAME_ISSUES[0]["reason"], "ambiguous_name")
        self.assertEqual(engine.NAME_ISSUES[0]["candidates"], ["你的寒冰箭", "记录者"])

    def test_player_named_you_is_not_replaced(self) -> None:
        configure({"你": "战士", "记录者": "德鲁伊"})
        self.assertEqual(engine.normalize_unit("你"), "你")
        self.assertEqual(engine.NAME_ISSUES[0]["chosen"], "你")

    def test_presence_limits_blame_to_attended_encounters(self) -> None:
        configure({"张三": "法师", "张三丰": "战士", "记录者": "德鲁伊"})
        engine.ATTEMPTS = {
            "首领甲": [{"attempt": 1, "result": "击杀", "start": "19:01:00.000", "end": "19:02:00.000"}],
            "首领乙": [{"attempt": 1, "result": "击杀", "start": "19:06:00.000", "end": "19:07:00.000"}],
        }
        rows = [
            {"sec": engine.seconds("19:01:30.000"), "body": "张三丰的旋风斩击中首领甲造成100点伤害。"},
            {"sec": engine.seconds("19:03:00.000"), "body": "张三的火球术击中首领甲造成100点伤害。"},
            {"sec": engine.seconds("19:06:30.000"), "body": "张三的火球术击中首领乙造成100点伤害。"},
        ]
        engine.PRESENCE = engine.compute_presence(rows, {"张三", "张三丰", "记录者"})
        self.assertFalse(engine.present_in("张三", "首领甲"))
        self.assertTrue(engine.present_in("张三", "首领乙"))
        self.assertTrue(engine.present_in("张三丰", "首领甲"))
        self.assertFalse(engine.present_in("张三丰", "首领乙"))
        self.assertTrue(engine.present_in("记录者", "首领乙"))
        self.assertEqual(engine.left_at("张三丰"), engine.seconds("19:01:30.000"))
        engine.PRESENCE = {}

    def test_prefix_name_uses_longest_match(self) -> None:
        configure({"张三": "法师", "张三丰": "战士", "记录者": "德鲁伊"})
        roster = {"张三", "张三丰", "记录者"}
        self.assertEqual(engine.split_source("张三丰的旋风斩", roster), ("张三丰", "旋风斩"))
        self.assertEqual(engine.split_source("张三的火球术", roster), ("张三", "火球术"))

    def test_known_unit_with_possessive_char(self) -> None:
        configure({"记录者": "德鲁伊"})
        self.assertEqual(engine.split_source("苍白的骑兵", {"记录者"}), ("苍白的骑兵", "近战"))

    def test_pet_owner_pronoun(self) -> None:
        configure({"记录者": "德鲁伊"})
        self.assertEqual(engine.normalize_unit("小猫 (你)"), "记录者")


def rows() -> list[dict]:
    lines = [
        (10, "19:00:00.000", "张三对训练首领造成了10点伤害。"),
        (11, "19:00:01.500", "训练首领开始施放毁灭。"),
        (12, "19:00:02.000", "张三受到了毁灭效果的影响。"),
        (13, "19:00:03.000", "你的愈合治疗了张三。"),
    ]
    return [{"line": line, "ts": ts, "sec": engine.seconds(ts), "body": body} for line, ts, body in lines]


class EvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.encounters = [("训练首领", "19:00:00.000", "19:05:00.000")]

    def attach(self, item: dict, logger: str = "记录者") -> dict:
        return attach_evidence([item], rows(), encounters=self.encounters, logger=logger, prefixes={"训练首领": "dummy"})[0]

    def test_timestamp_and_offset_map_to_player_lines(self) -> None:
        finding = self.attach({
            "player": "张三", "boss": "训练首领", "issue": "中毁灭", "weight": 1,
            "sources": [{"ts": "19:00:02.000", "damage_offset": 0.0, "damage": 10}],
        })
        self.assertEqual(finding["finding_id"], "dummy.中毁灭.001")
        self.assertEqual([item["line"] for item in finding["evidence_lines"]], [12, 10])
        self.assertEqual(finding["confidence"], "high")
        self.assertEqual(finding["values"]["damage"], 10)

    def test_logger_evidence_uses_pronoun_line(self) -> None:
        finding = self.attach({
            "player": "记录者", "boss": "训练首领", "issue": "治疗", "weight": 1,
            "sources": [{"ts": "19:00:03.000"}],
        })
        self.assertEqual(finding["evidence_lines"][0]["line"], 13)

    def test_absence_check_cites_pull_line(self) -> None:
        finding = self.attach({
            "player": "李四", "boss": "训练首领", "issue": "开打缺少药剂", "weight": 1,
            "sources": [{"item": "药剂"}],
        })
        self.assertEqual(finding["evidence_lines"][0]["purpose"], "开怪时刻")
        self.assertEqual(finding["confidence"], "high")

    def test_mechanic_line_when_player_absent(self) -> None:
        finding = self.attach({
            "player": "李四", "boss": "训练首领", "issue": "未转火", "weight": 1,
            "sources": [{"spawn_offset": 1.5}],
        })
        self.assertEqual(finding["evidence_lines"][0]["line"], 11)


def report(counts: dict[str, int]) -> dict:
    ranking = [
        {"player": name, "count": count, "details": ([{"issue": "训练首领·x", "count": count}] if count else [])}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"metadata": {"date": "2026-11-18", "roster": sorted(counts)}, "error_summary": {"ranking": ranking}}


def findings(counts: dict[str, int]) -> list[dict]:
    result = []
    for name, count in counts.items():
        for index in range(count):
            result.append({
                "finding_id": f"dummy.x.{name}.{index}", "rule_id": "dummy.x", "player": name,
                "weight": 1, "confidence": "high", "evidence_lines": [{"line": 1}],
            })
    return result


class ValidateTest(unittest.TestCase):
    def test_consistent_result_passes(self) -> None:
        counts = {"张三": 2, "李四": 0}
        result = validate(report(counts), findings(counts), {"date": "2026-11-18"}, golden={"available": False})
        self.assertTrue(result["ok"], result["failed"])

    def test_missing_finding_fails(self) -> None:
        counts = {"张三": 2, "李四": 0}
        result = validate(report(counts), findings({"张三": 1}), {"date": "2026-11-18"}, golden={"available": False})
        self.assertIn("findings.match_ranking", result["failed"])

    def test_golden_diff_and_placeholder_fail(self) -> None:
        counts = {"张三": 0}
        result = validate(
            report(counts), [], {"date": "2026-11-18", "title": "None"},
            golden={"available": True, "total": 3},
        )
        self.assertIn("golden.diff", result["failed"])
        self.assertIn("display.no_placeholder", result["failed"])


class CompareTest(unittest.TestCase):
    def test_unordered_lists_do_not_diff(self) -> None:
        left = {"buffs": [{"provider_candidates": ["乙", "甲"]}]}
        right = {"buffs": [{"provider_candidates": ["甲", "乙"]}]}
        self.assertEqual(summarize_diff(left, right)["total"], 2)
        paths = ["$.buffs[].provider_candidates"]
        self.assertEqual(summarize_diff(normalize_unordered(left, paths), normalize_unordered(right, paths))["total"], 0)


HOME = """<div class="reports">
        <a class="report" href="reports/2026-11-18/" style="animation-delay:0ms">
        </a>
        <a class="report" href="reports/2026-11-12/" style="animation-delay:70ms">
        </a>
      </div>
<span class="count">共 2 份报告</span>
"""


class SiteTest(unittest.TestCase):
    def test_home_card_inserted_by_date(self) -> None:
        html = add_home_card(HOME, "2026-11-15")
        order = [part.split("/")[0] for part in html.split('href="reports/')[1:]]
        self.assertEqual(order, ["2026-11-18", "2026-11-15", "2026-11-12"])
        self.assertIn("共 3 份报告", html)
        self.assertEqual(add_home_card(html, "2026-11-15"), html)

    def test_gate_blocks_without_review_and_accepts_matching_review(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "site").mkdir()
            (stage / "site" / "data.json").write_text("{}", encoding="utf-8")
            display = "sha256:" + sha256_file(stage / "site" / "data.json")
            (stage / "validation.json").write_text(json.dumps({"ok": True, "failed": []}), encoding="utf-8")
            pack = {"input_hashes": {"display": display}, "findings": [
                {"example": {"finding_id": "dummy.x.001"}, "others": [["dummy.x.002"]]},
            ]}
            (stage / "review-pack.json").write_text(json.dumps(pack), encoding="utf-8")
            self.assertIn("缺少 AI 复核结果 review-result.json", check_gate(stage))
            review = {
                "input_hashes": {"review_pack": "sha256:" + sha256_file(stage / "review-pack.json")},
                "status": "approved",
                "items": [{"finding_id": "dummy.x.001", "status": "approved"}],
                "global_issues": [],
            }
            (stage / "review-result.json").write_text(json.dumps(review), encoding="utf-8")
            self.assertEqual(check_gate(stage), ["复核包中有 1 条未复核"])
            review["items"].append({"finding_id": "dummy.x.002", "status": "needs_change"})
            (stage / "review-result.json").write_text(json.dumps(review), encoding="utf-8")
            self.assertTrue(any("未通过" in item for item in check_gate(stage)))
            review["items"][1]["status"] = "approved"
            (stage / "review-result.json").write_text(json.dumps(review), encoding="utf-8")
            self.assertEqual(check_gate(stage), [])
            (stage / "site" / "data.json").write_text('{"changed": 1}', encoding="utf-8")
            self.assertIn("网站数据与复核包不是同一次运行", check_gate(stage))


if __name__ == "__main__":
    unittest.main()
