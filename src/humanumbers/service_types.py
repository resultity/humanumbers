from __future__ import annotations

from dataclasses import dataclass


class HumanizeError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedInput:
    raw_text: str
    normalized_text: str
    value: float
    unit: str
    family: str
    matched_alias: str | None
    fuzzy_score: float | None
    count_noun: str | None = None


@dataclass(frozen=True)
class Candidate:
    text: str
    score: float
    rule_kind: str
    style: str
    roughness: str
