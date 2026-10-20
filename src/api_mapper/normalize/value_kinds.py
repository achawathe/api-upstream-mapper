"""What kind of data a field holds: read from sample values for a source, from format and definition for a target.

Samples can be partial, so a kind seen in them only supports or contradicts a match; it never
makes one. A contradiction needs every observed value to disagree.
"""

import re
from datetime import date, datetime
from typing import Any

from api_mapper.models import FieldNode
from api_mapper.normalize.definitions import leading_definition

DATE, DATE_TIME, CURRENCY, UUID, EMAIL, URL, NUMBER, BOOLEAN, TEXT = (
    "date",
    "date-time",
    "currency code",
    "uuid",
    "email",
    "url",
    "number",
    "boolean",
    "text",
)
# Kinds narrow enough that agreement says something about meaning, not just type.
SPECIFIC = frozenset({DATE, DATE_TIME, CURRENCY, UUID, EMAIL, URL})
_TEMPORAL = frozenset({DATE, DATE_TIME})
_FORMATS = {"date": DATE, "date-time": DATE_TIME, "uuid": UUID, "email": EMAIL, "uri": URL, "url": URL}
_CURRENCY_DEFINITION = re.compile(r"\biso[ -]?4217\b|\bcurrency code\b", re.IGNORECASE)
_PATTERNS = (
    (CURRENCY, re.compile(r"^[A-Z]{3}$")),
    (UUID, re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)),
    (EMAIL, re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")),
    (URL, re.compile(r"^https?://\S+$")),
    (NUMBER, re.compile(r"^-?\d+(?:\.\d+)?$")),
)


def expected_kind(node: FieldNode) -> str | None:
    if node.format in _FORMATS:
        return _FORMATS[node.format]
    definitions = (node.description, *(clue.text for clue in node.documentation))
    if node.type == "string" and any(_CURRENCY_DEFINITION.search(leading_definition(text)) for text in definitions):
        return CURRENCY
    if node.type in ("number", "integer"):
        return NUMBER
    return None


def observed_kind(node: FieldNode) -> tuple[str, Any] | None:
    """The single kind every sample value has, with one value to quote; None without samples or when they mix."""
    values = [v for v in (*node.observed, node.example) if v is not None]
    kinds = {_kind(v) for v in values}
    if len(kinds) == 2 and kinds <= _TEMPORAL:
        kinds = {DATE_TIME}
    return (next(iter(kinds)), values[0]) if len(kinds) == 1 else None


def contradiction(expected: str | None, seen: str | None) -> bool:
    if expected is None or seen is None or expected == seen:
        return False
    if expected == NUMBER:
        return True
    if expected in _TEMPORAL:
        return seen not in (*_TEMPORAL, NUMBER)
    if expected == CURRENCY:
        return seen != NUMBER
    return expected in SPECIFIC


def agreement(expected: str | None, seen: str | None) -> bool:
    if expected not in SPECIFIC or seen is None:
        return False
    return expected == seen or {expected, seen} <= _TEMPORAL


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, (int, float)):
        return NUMBER
    text = str(value)
    if (temporal := _temporal(text)) is not None:
        return temporal
    return next((kind for kind, pattern in _PATTERNS if pattern.match(text)), TEXT)


def _temporal(text: str) -> str | None:
    if len(text) < 10 or text[4:5] != "-" or text[7:8] != "-":
        return None
    try:
        if len(text) == 10:
            date.fromisoformat(text)
            return DATE
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return DATE_TIME
    except ValueError:
        return None
