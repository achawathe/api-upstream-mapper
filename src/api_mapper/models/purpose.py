"""Traceable observations and explicit vocabulary for a field's intended use."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextClue:
    text: str
    location: str


@dataclass(frozen=True)
class ValueProfile:
    count: int = 0
    distinct: int = 0
    digit_strings: int = 0
    text_labels: int = 0


@dataclass(frozen=True)
class PurposeRule:
    group: str
    role: str
    label: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class PurposeFact:
    group: str
    role: str
    label: str
    location: str
    quote: str
