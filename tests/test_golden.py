"""黄金基准快照一旦冻结，就和哈希、关键指标互相核对。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from karazhan_tool.hashing import sha256_file

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "golden" / "2026-11-18"


class GoldenBaselineTest(unittest.TestCase):
    def test_frozen_files_match_recorded_hashes(self) -> None:
        hashes = json.loads((GOLDEN / "hashes.json").read_text(encoding="utf-8"))
        for name, record in hashes["files"].items():
            self.assertEqual(sha256_file(GOLDEN / name), record["sha256"])

    def test_key_metrics(self) -> None:
        metrics = json.loads((GOLDEN / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["date"], "2026-11-18")
        self.assertEqual(metrics["roster_size"], 41)
        self.assertEqual(len(metrics["roster"]), 41)
        self.assertEqual(metrics["error_ranking"][0]["player"], "湘江之畔")
        self.assertEqual(metrics["error_ranking"][0]["count"], 20)
        self.assertEqual(metrics["dps"]["active_combat_time"], 3104.623)
        self.assertEqual(metrics["dps"]["players"][0]["name"], "妖肆贰")
        self.assertEqual(metrics["wipe_causes"][0]["encounter"], "桑夫·塔斯达尔第1次尝试")
        self.assertTrue(metrics["zero_error"])


@unittest.skipUnless(os.environ.get("KARAZHAN_FULL") == "1", "完整回归需读取原始日志，设置 KARAZHAN_FULL=1 运行")
class FullGoldenRegressionTest(unittest.TestCase):
    def test_new_tool_reproduces_golden_analysis_and_display(self) -> None:
        from karazhan_tool.analyze import load_rules, normalize_unordered, run_analysis
        from karazhan_tool.cli import _freeze
        from karazhan_tool.compare import summarize_diff
        from karazhan_tool.config import load_config
        from karazhan_tool.render.model import build_model

        root = GOLDEN.parents[2]
        config = load_config(root / "config" / "raids" / "2026-11-18.json")
        rules = load_rules(root / "config" / "rules.json")
        result = run_analysis(config, _freeze(config).roster, rules)
        paths = rules["unordered_golden_paths"]
        expected = normalize_unordered(json.loads((GOLDEN / "analysis.json").read_text(encoding="utf-8")), paths)
        actual = normalize_unordered(json.loads(json.dumps(result.report, ensure_ascii=False)), paths)
        self.assertEqual(summarize_diff(expected, actual)["total"], 0)
        notes = config.raw["analysis"]["display_notes"]
        display = json.dumps(build_model(result.report, notes), ensure_ascii=False, indent=2) + "\n"
        self.assertEqual(display.encode("utf-8"), (GOLDEN / "display.json").read_bytes())
        self.assertEqual(sum(item["weight"] for item in result.findings), 374)
        self.assertTrue(all(item["evidence_lines"] for item in result.findings))
