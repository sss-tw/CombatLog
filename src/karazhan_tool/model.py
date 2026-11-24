"""分析工具的稳定数据对象。"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Player:
    guid: str | None
    name: str
    class_id: str | None
    class_name: str | None
    sources: tuple[str, ...]
    confirmed: bool

    def to_dict(self) -> dict:
        return {
            "guid": self.guid,
            "name": self.name,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "sources": list(self.sources),
            "confirmed": self.confirmed,
        }


@dataclass(frozen=True)
class NameCandidate:
    kind: str
    name: str | None
    guid: str | None
    spell: str | None
    pet: str | None
    reason: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "guid": self.guid,
            "spell": self.spell,
            "pet": self.pet,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NameResolution:
    """一次姓名解析结果。无法唯一确定时保留全部候选。"""

    status: str
    method: str
    name: str | None
    guid: str | None
    spell: str | None
    pet: str | None
    candidates: tuple[NameCandidate, ...]
    flags: tuple[str, ...]
    confidence: str
    raw: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "method": self.method,
            "name": self.name,
            "guid": self.guid,
            "spell": self.spell,
            "pet": self.pet,
            "candidates": [item.to_dict() for item in self.candidates],
            "flags": list(self.flags),
            "confidence": self.confidence,
            "raw": self.raw,
        }
