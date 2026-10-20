"""Deterministic string normalization and collision checks for reviewed value maps."""

import re
from typing import Any

from api_mapper.models import FieldNode, TransformKind, TransformStep
from api_mapper.normalize.enum_contract import enum_contract

MODES = frozenset({"exact", "trim-case", "trim-case-separators"})


def normalized_key(value: str, mode: str) -> str:
    if mode == "exact":
        return value
    value = value.strip().casefold()
    return re.sub(r"[\s_-]+", " ", value) if mode == "trim-case-separators" else value


def normalized_mapping(mapping: dict[str, str], mode: str) -> dict[str, str]:
    if mode not in MODES:
        raise ValueError("Choose a supported string normalization mode")
    result = {}
    for source, target in mapping.items():
        key = normalized_key(source, mode)
        if key in result and result[key] != target:
            raise ValueError(f"Normalization makes {source!r} ambiguous; choose one output or use exact matching")
        result[key] = target
    return result


def translate_value(params: dict, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("Value translation expects a string; add a type conversion first")
    mode = params.get("normalization", "exact")
    mapping = normalized_mapping(params.get("mapping", {}), mode)
    key = normalized_key(value, mode)
    if key in mapping:
        return mapping[key]
    if "fallback" in params:
        return params["fallback"]
    raise ValueError(f"no upstream value for {value!r}; add a translation or choose an explicit fallback")


def validate_enum_outputs(steps: tuple[TransformStep, ...] | None, target: FieldNode) -> None:
    contract = enum_contract(target)
    for step in steps or ():
        if step.kind is not TransformKind.ENUM_MAP:
            continue
        outputs = list(step.params.get("mapping", {}).values())
        if "fallback" in step.params:
            outputs.append(step.params["fallback"])
        if contract.values and any(output not in contract.values for output in outputs):
            raise ValueError(
                "Value translations must use allowed outputs from the target specification or documentation"
            )
        if "fallback" in step.params and not contract.values:
            raise ValueError("A fallback requires an allowed output set from the specification or documentation")
