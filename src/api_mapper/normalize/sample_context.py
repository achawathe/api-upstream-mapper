"""Summarise documentation values for local embeddings without inferring field ownership."""

import re
from datetime import date, datetime
from typing import Any

_LABEL = re.compile(r"[A-Za-z][A-Za-z _/-]{1,39}")
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def describe_samples(values: list[Any]) -> str:
    hints = list(dict.fromkeys(hint for value in values if (hint := _hint(value))))
    return "Documentation response examples: " + "; ".join(hints[:3]) + "." if hints else ""


def _hint(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean values"
    if isinstance(value, (int, float)):
        return "numeric values"
    if not isinstance(value, str):
        return ""
    try:
        if len(value) == 10:
            date.fromisoformat(value)
            return "ISO calendar dates"
        if "T" in value:
            datetime.fromisoformat(value)
            return "ISO timestamps"
    except ValueError:
        pass
    if _UUID.fullmatch(value):
        return "UUID identifiers"
    if _LABEL.fullmatch(value):
        return f"label {value}"
    return ""
