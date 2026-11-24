"""装备奥抗查表。物品数据是合成的。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from karazhan_tool.items import normalize_item_name, parse_equipment, tooltip_arcane_resistance
from karazhan_tool.rules import engine


class ItemResistTests(unittest.TestCase):
    def test_tooltip_counts_static_lines_only(self) -> None:
        pre = "<br>+15 Arcane Resistance<br>+5 All Resistances"
        bonus = "Use: Increases Arcane Resistance by 50 for 1 min."
        self.assertEqual(tooltip_arcane_resistance(pre, bonus), 20)
        self.assertEqual(tooltip_arcane_resistance(None, None), 0)

    def test_name_normalization(self) -> None:
        self.assertEqual(normalize_item_name("Someone\\'s Belt"), "Someone's Belt")
        self.assertEqual(normalize_item_name("Green Shirt "), "Green Shirt")

    def test_parse_equipment(self) -> None:
        self.assertEqual(parse_equipment("甲;100:0:0:0:0&乙;200:5:0:0:0&坏"), [(100, "甲"), (200, "乙")])

    def test_unresolved_items_are_reported(self) -> None:
        items, names = dict(engine.ARCANE_RESIST_ITEMS), dict(engine.ARCANE_RESIST_NAMES)
        try:
            engine.ARCANE_RESIST_ITEMS.clear()
            engine.ARCANE_RESIST_ITEMS.update({100: 30, 101: 0})
            engine.ARCANE_RESIST_NAMES.clear()
            engine.ARCANE_RESIST_NAMES.update({"Odd's Ring": 15})
            total, components, unresolved = engine.arcane_resist_from_equipment(
                "甲;100:0:0:0:0&乙;101:0:0:0:0&Odd's Ring ;9999999:0:0:0:0&丙;102:0:0:0:0"
            )
        finally:
            engine.ARCANE_RESIST_ITEMS.clear(); engine.ARCANE_RESIST_ITEMS.update(items)
            engine.ARCANE_RESIST_NAMES.clear(); engine.ARCANE_RESIST_NAMES.update(names)
        self.assertEqual(total, 45)
        self.assertEqual(components, ["甲 +30", "Odd's Ring  +15"])
        self.assertEqual(unresolved, ["丙"])


if __name__ == "__main__":
    unittest.main()
