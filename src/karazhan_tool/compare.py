"""JSON 逐字段对比。只返回差异路径和简短取值，避免整份输出。"""

from __future__ import annotations

import json
from typing import Any, Iterator

_TEXT_LIMIT = 80


def diff(expected: Any, actual: Any, path: str = "$") -> Iterator[tuple[str, str, str]]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in expected:
            child = f"{path}.{key}"
            if key not in actual:
                yield child, _short(expected[key]), "<缺少>"
            else:
                yield from diff(expected[key], actual[key], child)
        for key in actual:
            if key not in expected:
                yield f"{path}.{key}", "<缺少>", _short(actual[key])
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            yield f"{path}.length", str(len(expected)), str(len(actual))
        for index, (left, right) in enumerate(zip(expected, actual)):
            yield from diff(left, right, f"{path}[{index}]")
        return
    if expected != actual:
        yield path, _short(expected), _short(actual)


def summarize_diff(expected: Any, actual: Any, limit: int = 40) -> dict:
    """按顶层分区计数，并给出前 limit 条差异。"""
    sections: dict[str, int] = {}
    samples: list[dict] = []
    total = 0
    for path, left, right in diff(expected, actual):
        total += 1
        section = _section(path)
        sections[section] = sections.get(section, 0) + 1
        if len(samples) < limit:
            samples.append({"path": path, "expected": left, "actual": right})
    return {"total": total, "sections": sections, "samples": samples}


def _section(path: str) -> str:
    parts = path[2:].replace("[", ".[").split(".")
    head = [part for part in parts[:2] if part and not part.startswith("[")]
    return ".".join(head) or "$"


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) > _TEXT_LIMIT:
        return text[:_TEXT_LIMIT] + "…"
    return text
