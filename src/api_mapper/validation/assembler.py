"""Builds an upstream response body from downstream responses and the chosen mappings.

Values are read as nested lists, one level per array on the source path. The shape is
then aligned to the target path: equal depth copies item by item, a shallower source is
repeated into every item (broadcast), and a fan-out call adds one level (one response
per item).
"""

from dataclasses import dataclass, field
from typing import Any

from api_mapper.models import FieldMapping
from api_mapper.transforms.apply import TransformError, apply_transforms


@dataclass(frozen=True)
class Broadcast:
    value: Any


@dataclass
class AssemblyNotes:
    issues: list[str] = field(default_factory=list)


def extract(document: Any, path: str) -> Any:
    segments = path.split(".")

    def walk(node: Any, index: int) -> Any:
        if index == len(segments):
            return node
        segment = segments[index]
        name, is_array = segment.removesuffix("[]"), segment.endswith("[]")
        if name:
            node = node.get(name) if isinstance(node, dict) else None
        if node is None:
            return None
        if is_array:
            return [walk(item, index + 1) for item in node] if isinstance(node, list) else None
        return walk(node, index + 1)

    return walk(document, 0)


def align(value: Any, source_depth: int, target_depth: int) -> Any:
    if source_depth == target_depth:
        return value
    if source_depth < target_depth:
        return Broadcast(align(value, source_depth, target_depth - 1))
    first = value[0] if isinstance(value, list) and value else None
    return align(first, source_depth - 1, target_depth)


def transform_nested(value: Any, mapping: FieldMapping, notes: AssemblyNotes, indices: tuple[int, ...] = ()) -> Any:
    if isinstance(value, Broadcast):
        return Broadcast(transform_nested(value.value, mapping, notes, indices))
    if isinstance(value, list):
        return [transform_nested(item, mapping, notes, (*indices, i)) for i, item in enumerate(value)]
    if value is None:
        return None
    try:
        return apply_transforms(mapping.chosen.transforms, value)
    except (TransformError, ValueError, TypeError) as error:
        notes.issues.append(f"{_indexed(mapping.target.path, indices)}: {error}")
        return None


def _indexed(path: str, indices: tuple[int, ...]) -> str:
    for index in indices:
        path = path.replace("[]", f"[{index}]", 1)
    return path


def write(document: dict, path: str, value: Any) -> None:
    _write(document, path.split("."), value)


def _write(node: Any, segments: list[str], value: Any) -> None:
    segment, rest = segments[0], segments[1:]
    name, is_array = segment.removesuffix("[]"), segment.endswith("[]")
    if not is_array:
        if not rest:
            if value is not None:
                node[name] = value
            return
        _write(node.setdefault(name, {}), rest, value)
        return

    items = node.setdefault(name, []) if name else node
    if isinstance(value, Broadcast):
        if not items:
            items.append(_empty_item(rest))
        for index in range(len(items)):
            _write_item(items, index, rest, value.value)
        return
    if not isinstance(value, list):
        return
    while len(items) < len(value):
        items.append(_empty_item(rest))
    for index, item_value in enumerate(value):
        _write_item(items, index, rest, item_value)


def _write_item(items: list, index: int, rest: list[str], value: Any) -> None:
    if value is None:
        return
    if rest:
        _write(items[index], rest, value)
    else:
        items[index] = value


def _empty_item(rest: list[str]) -> Any:
    if not rest:
        return None
    return [] if rest[0] == "[]" else {}
