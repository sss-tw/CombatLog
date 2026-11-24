"""从物品数据库导出装备自带奥术抗性表。"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from karazhan_tool.hashing import sha256_file

_ARCANE = re.compile(r"\+(-?\d+) Arcane Resistance")
_ALL = re.compile(r"\+(-?\d+) All Resistances")


def normalize_item_name(name: str) -> str:
    """库里撇号存成 \\'，日志里可能带尾随空格。"""
    return name.replace("\\'", "'").replace("’", "'").strip()


def tooltip_arcane_resistance(*parts: str | None) -> int:
    """只认静态属性行“+N Arcane Resistance”和“+N All Resistances”，使用和触发效果不算。"""
    text = " ".join(part or "" for part in parts)
    return sum(int(value) for value in _ARCANE.findall(text)) + sum(int(value) for value in _ALL.findall(text))


def parse_equipment(equipment: str) -> list[tuple[int, str]]:
    """COMBATANT_INFO 装备串：名称;物品ID:附魔:词缀:...，以 & 分隔。"""
    items = []
    for slot in equipment.split("&"):
        if ";" not in slot:
            continue
        name, code = slot.rsplit(";", 1)
        try:
            items.append((int(code.split(":")[0]), name))
        except ValueError:
            continue
    return items


def scan_equipment(custom_data_files: list[Path]) -> set[tuple[int, str]]:
    seen: set[tuple[int, str]] = set()
    for path in custom_data_files:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if "|COMBATANT_INFO|" not in line:
                    continue
                fields = line.rstrip("\n").split("|")
                if len(fields) >= 11:
                    seen.update(parse_equipment(fields[10]))
    return seen


def _load_db(db_path: Path) -> tuple[dict[int, int], dict[str, set[int]]]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT i.item_id, i.name, l.name, t.pre_html, t.bonus_html "
            "FROM items i LEFT JOIN item_tooltip_stats t ON t.item_id = i.item_id "
            "LEFT JOIN entity_localizations l "
            "ON l.entity_type = 'item' AND l.entity_id = i.item_id AND l.locale = 'zhCN'"
        ).fetchall()
    finally:
        connection.close()
    by_id: dict[int, int] = {}
    by_name: dict[str, set[int]] = {}
    for item_id, name, name_zh, pre, bonus in rows:
        if pre is None and bonus is None:
            continue
        value = tooltip_arcane_resistance(pre, bonus)
        by_id[item_id] = value
        for label in {name, name_zh} - {None, ""}:
            by_name.setdefault(normalize_item_name(label), set()).add(value)
    return by_id, by_name


def export_arcane_items(db_path: Path, custom_data_files: list[Path]) -> dict:
    by_id, by_name = _load_db(db_path)
    items: dict[str, dict] = {}
    names: dict[str, int] = {}
    pending: dict[str, str] = {}
    for item_id, name in sorted(scan_equipment(custom_data_files)):
        if item_id in by_id:
            items[str(item_id)] = {"name": name, "arcane": by_id[item_id]}
            continue
        values = by_name.get(normalize_item_name(name))
        if values and len(values) == 1:
            names[normalize_item_name(name)] = next(iter(values))
        else:
            pending[str(item_id)] = name
    for item_id, value in by_id.items():
        if value and str(item_id) not in items:
            items[str(item_id)] = {"name": None, "arcane": value}
    return {
        "schema_version": 1,
        "source": str(db_path),
        "source_sha256": "sha256:" + sha256_file(db_path),
        "rule": "物品提示静态属性 +N Arcane Resistance 与 +N All Resistances 之和；先按物品ID查，ID不在库中时按唯一的中英文名查。"
        "items 收录库中全部带奥抗装备和日志中出现过的装备（0 表示核实无奥抗）；pending 为库中查不到、需人工补的装备。",
        "items": dict(sorted(items.items(), key=lambda item: int(item[0]))),
        "names": dict(sorted(names.items())),
        "pending": dict(sorted(pending.items(), key=lambda item: int(item[0]))),
    }


def write_table(table: dict, path: Path) -> None:
    path.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
