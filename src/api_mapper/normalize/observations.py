"""Small factual value summaries; sample statistics never establish production guarantees."""

import json
import re
from typing import Any

from api_mapper.models.purpose import ContextClue, ValueProfile

_LABEL = re.compile(r"[A-Za-z][A-Za-z /-]{1,79}")


def summarize_values(values: list[Any]) -> ValueProfile:
    return ValueProfile(
        count=len(values),
        distinct=len({json.dumps(v, sort_keys=True) for v in values}),
        digit_strings=sum(isinstance(v, str) and v.isdigit() for v in values),
        text_labels=sum(isinstance(v, str) and bool(_LABEL.fullmatch(v)) and " " in v for v in values),
    )


def sibling_clues(records: list[Any], path: str, source: str, declared: set[str]) -> tuple[ContextClue, ...]:
    # Only an explicit value/meaning pair establishes this relationship. Do not copy
    # arbitrary neighboring descriptions onto every field in the object.
    parent, _, name = path.rpartition(".")
    if name != "value":
        return ()
    found = []
    for record in records:
        if not isinstance(record, dict) or name not in record or record[name] is None:
            continue
        for key in ("meaning", "description"):
            sibling = f"{parent}.{key}" if parent else key
            value = record.get(key)
            if sibling in declared and isinstance(value, str) and 0 < len(value) <= 160:
                found.append(ContextClue(value, f"{source}:{sibling}"))
    return tuple(dict.fromkeys(found))
