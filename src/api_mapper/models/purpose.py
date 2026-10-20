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
    """`expects_labels` marks purposes whose values are human-readable words, not codes.
    `match_names` lets a field's name state the purpose when the name alone is unambiguous
    (`merchantCategoryCode`); other rules read definitions only."""

    group: str
    role: str
    label: str
    patterns: tuple[str, ...]
    expects_labels: bool = False
    match_names: bool = False


@dataclass(frozen=True)
class PurposeFact:
    group: str
    role: str
    label: str
    location: str
    quote: str
    expects_labels: bool = False
