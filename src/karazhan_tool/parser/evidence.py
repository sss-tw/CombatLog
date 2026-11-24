"""按行号从原始日志取出短片段，避免把整份日志读进复核上下文。"""

from __future__ import annotations
from pathlib import Path


def read_lines(path: Path, line: int, *, before: int = 0, after: int = 0) -> list[dict]:
    if line < 1:
        raise ValueError("行号必须从 1 开始")
    if before < 0 or after < 0:
        raise ValueError("上下文行数不能为负")
    start = max(1, line - before)
    end = line + after
    found: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            if number < start:
                continue
            if number > end:
                break
            found.append({"line": number, "text": raw.rstrip("\n"), "focus": number == line})
    if not any(item["line"] == line for item in found):
        raise ValueError(f"日志没有第 {line} 行：{path}")
    return found


def read_many(path: Path, lines: list[int]) -> dict[int, str]:
    """一次顺序读取多行，返回 行号 -> 原文。"""
    wanted = set(lines)
    if not wanted:
        return {}
    last = max(wanted)
    found: dict[int, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            if number in wanted:
                found[number] = raw.rstrip("\n")
            if number >= last:
                break
    missing = wanted - set(found)
    if missing:
        raise ValueError(f"日志缺少行：{sorted(missing)[:5]}")
    return found
