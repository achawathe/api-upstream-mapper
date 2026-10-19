"""Checks an assembled response against the upstream field definitions."""

import re
from dataclasses import dataclass
from typing import Any

from api_mapper.models import FieldNode

_FORMATS = {
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "date-time": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"),
}
_JSON_TYPES = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


@dataclass(frozen=True)
class Issue:
    path: str
    message: str


def check_document(document: Any, fields: list[FieldNode], root_path: str = "") -> list[Issue]:
    issues: list[Issue] = []
    for field in fields:
        for location, present, value in _values(document, field.path.split("."), root_path):
            if not present:
                if field.required:
                    issues.append(Issue(location, "required field missing"))
                continue
            issues.extend(_check_value(field, location, value))
    return list(dict.fromkeys(issues))


def _values(node: Any, segments: list[str], location: str):
    """Yields (location, present, value) for every place the path reaches; stops below a missing optional parent."""
    if not segments:
        yield location, True, node
        return
    segment, rest = segments[0], segments[1:]
    name, is_array = segment.removesuffix("[]"), segment.endswith("[]")
    here = f"{location}.{name}" if location and name else (name or location)
    if name:
        if not isinstance(node, dict) or node.get(name) is None:
            yield here, False, None
            return
        node = node[name]
    if not is_array:
        yield from _values(node, rest, here)
        return
    if not isinstance(node, list):
        yield here, True, node
        return
    for index, item in enumerate(node):
        yield from _values(item, rest, f"{here}[{index}]")


def _check_value(field: FieldNode, location: str, value: Any) -> list[Issue]:
    if value is None:
        return [] if field.nullable or not field.required else [Issue(location, "null in a required field")]
    expected = _JSON_TYPES.get(field.type)
    if expected and (not isinstance(value, expected) or (field.type != "boolean" and isinstance(value, bool))):
        return [Issue(location, f"expected {field.type}, got {type(value).__name__} {value!r}")]
    if field.enum and str(value) not in field.enum:
        return [Issue(location, f"{value!r} is not one of the allowed values")]
    pattern = _FORMATS.get(field.format or "")
    if pattern and isinstance(value, str) and not pattern.match(value):
        return [Issue(location, f"{value!r} is not a valid {field.format}")]
    return []
