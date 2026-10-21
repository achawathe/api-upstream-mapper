"""Infers a JSON schema from example payloads.

A key is `required` only when every sample object has it; a value seen as null
anywhere makes the field nullable. Mixed scalar types fall back to the most
general type so inference never fails on messy data.

An object whose keys are data, such as cities, currency codes or account IDs,
becomes a map (`additionalProperties`) with its observed keys kept as examples.
"""

import re
from collections.abc import Sequence
from typing import Any

_GENERALITY = ("object", "array", "string", "number", "integer", "boolean")
MAP_KEYS_KEY = "x-map-keys"
MIN_MAP_KEYS = 3
MAX_SHARED_KEY_SHARE = 0.5
MIN_SHAPE_OVERLAP = 0.5
_VALUE_LIKE_KEY = re.compile(
    r"^(?:\d+(?:\.\d+)?"  # numbers
    r"|\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?"  # dates and timestamps
    r"|[A-Z]{3}"  # ISO-style codes: currencies, countries
    r"|(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+"  # IDs: ACC-1001, user_42
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
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
    if _is_map(objects):
        keys = list(dict.fromkeys(str(key) for obj in objects for key in obj))
        return {"additionalProperties": infer_schema([v for obj in objects for v in obj.values()]), MAP_KEYS_KEY: keys}
    keys: list[str] = []
    for obj in objects:
        keys.extend(k for k in obj if k not in keys)
    properties = {key: infer_schema([obj[key] for obj in objects if key in obj]) for key in keys}
    required = [key for key in keys if all(key in obj for obj in objects)]
    return {"properties": properties, "required": required}


def _is_map(objects: list[dict]) -> bool:
    """Keys are data when they change from sample to sample, or look like values, over same-shaped entries.

    Optional fields also come and go, so changing keys count only when most of them differ
    between samples. A single sample shows a map only through value-like keys.
    """
    union = list(dict.fromkeys(key for obj in objects for key in obj))
    if len(union) < MIN_MAP_KEYS or not _same_shape([v for obj in objects for v in obj.values()]):
        return False
    shared = set.intersection(*(set(obj) for obj in objects))
    varying = len(objects) > 1 and len(shared) / len(union) <= MAX_SHARED_KEY_SHARE
    return varying or all(_VALUE_LIKE_KEY.match(str(key)) for key in union)


def _same_shape(values: list[Any]) -> bool:
    present = [v for v in values if v is not None]
    if not present:
        return False
    types = {_json_type(v) for v in present}
    if types == {"integer", "number"}:
        return True
    if len(types) != 1:
        return False
    if types != {"object"}:
        return True
    key_sets = [set(v) for v in present]
    common = set.intersection(*key_sets)
    union = set.union(*key_sets)
    return bool(union) and len(common) / len(union) >= MIN_SHAPE_OVERLAP


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
