"""Use an input's resource identity independently of JSON envelope names."""

from api_mapper.models import Parameter
from api_mapper.normalize.lexicon import Lexicon


def input_name(parameter: Parameter, lexicon: Lexicon) -> str:
    if parameter.location != "body":
        return parameter.name
    segments = parameter.name.split(".")
    leaf = segments[-1]
    if len(segments) > 1 and lexicon.is_generic(lexicon.concepts(leaf)):
        return ".".join(segments[-2:])
    return leaf


def bindable_body(parameter: Parameter) -> bool:
    schema = parameter.schema
    if parameter.context_only or parameter.name == "$body" or schema.get("oneOf") or schema.get("anyOf"):
        return False
    if schema.get("type") == "array":
        return schema.get("items", {}).get("type") in {"string", "integer", "number", "boolean"}
    return schema.get("type") in {"string", "integer", "number", "boolean"}


def compatible_body_input(source: dict, target: dict) -> bool:
    """Direct bindings do not guess coercions, date conversions or enum translations."""
    if target.get("type") == "array":
        target = target.get("items") or {}
        if source.get("type") == "array":
            source = source.get("items") or {}
    source_type, target_type = source.get("type"), target.get("type")
    if not source_type or source_type != target_type:
        return False
    if source.get("format") != target.get("format"):
        return False
    allowed = target.get("enum")
    return not allowed or bool(source.get("enum")) and set(source["enum"]) <= set(allowed)
