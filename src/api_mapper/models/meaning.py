"""Domain-defined distinctions between fields that share vocabulary but mean different things."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MeaningRule:
    group: str
    role: str
    concepts: frozenset[str]
    name_phrases: tuple[str, ...] = ()
    definition_phrases: tuple[str, ...] = ()
