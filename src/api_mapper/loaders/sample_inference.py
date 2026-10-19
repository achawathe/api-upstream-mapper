"""Infers a JSON schema from example payloads.

A key is `required` only when every sample object has it; a value seen as null
anywhere makes the field nullable. Mixed scalar types fall back to the most
general type so inference never fails on messy data.
"""

import re
from collections.abc import Sequence
from typing import Any

_GENERALITY = ("object", "array", "string", "number", "integer", "boolean")
_FORMAT_PATTERNS = (
    ("date-time", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")),
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("uuid", re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")),
    ("email", re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")),
)


def infer_schema(samples: Sequence[Any]) -> dict[str, Any]:
    values = [s for s in samples if s is not None]
    nullable = len(values) < len(samples)
    if not values:
        return {"type": "string", "nullable": True}

    types = {_json_type(v) for v in values}
    if types == {"integer", "number"}:
        types = {"number"}
    chosen = next(t for t in _GENERALITY if t in types)
    schema: dict[str, Any] = {"type": chosen}
    if len(types) > 1:
        schema["x-mixed-types"] = sorted(types)

    if chosen == "object":
        schema.update(_object_schema([v for v in values if isinstance(v, dict)]))
    elif chosen == "array":
        items = [item for v in values if isinstance(v, list) for item in v]
        schema["items"] = infer_schema(items) if items else {}
    else:
        schema["example"] = values[0]
        if chosen == "string":
            detected = _detect_format([v for v in values if isinstance(v, str)])
            if detected:
                schema["format"] = detected
    if nullable:
        schema["nullable"] = True
    return schema


def _object_schema(objects: list[dict]) -> dict[str, Any]:
    keys: list[str] = []
    for obj in objects:
        keys.extend(k for k in obj if k not in keys)
    properties = {key: infer_schema([obj[key] for obj in objects if key in obj]) for key in keys}
    required = [key for key in keys if all(key in obj for obj in objects)]
    return {"properties": properties, "required": required}


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"


def _detect_format(strings: list[str]) -> str | None:
    for format_name, pattern in _FORMAT_PATTERNS:
        if strings and all(pattern.match(s) for s in strings):
            return format_name
    return None
