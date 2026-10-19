"""Turns resolved response schemas into leaf FieldNodes.

oneOf/anyOf branches become variants, so `accountId` inside `LoanAccount` and inside
`DepositAccount` are separate targets that can map to different downstream APIs.
"""

from dataclasses import dataclass, replace
from typing import Any

from api_mapper.loaders.ref_resolver import CYCLE_KEY, SCHEMA_NAME_KEY, UNRESOLVED_KEY
from api_mapper.models import ApiSpec, Endpoint, FieldNode
from api_mapper.normalize.sample_context import describe_samples

MAX_DEPTH = 24
MAP_KEY_SEGMENT = "{key}"
MAX_OBSERVED_VALUES = 20


@dataclass(frozen=True)
class _Context:
    path: str = ""
    required: bool = True
    nullable: bool = False
    variant: str | None = None
    conditions: tuple[tuple[str, str], ...] = ()
    schema_names: tuple[str, ...] = ()
    array_depth: int = 0
    depth: int = 0

    def child(self, segment: str, required: bool) -> "_Context":
        path = f"{self.path}.{segment}" if self.path else segment
        return replace(self, path=path, required=self.required and required, depth=self.depth + 1)

    def array_items(self) -> "_Context":
        """`tags[]` for an array; `matrix[].[]` for an array of arrays, so every level is one path segment."""
        path = f"{self.path}.[]" if self.path.endswith("[]") else f"{self.path}[]"
        return replace(self, path=path, array_depth=self.array_depth + 1, depth=self.depth + 1)

    def named(self, schema_name: str | None) -> "_Context":
        if not schema_name or schema_name in self.schema_names[-1:]:
            return self
        return replace(self, schema_names=(*self.schema_names, schema_name))

    def in_variant(self, label: str, condition: tuple[str, str] | None) -> "_Context":
        variant = f"{self.variant}/{label}" if self.variant else label
        conditions = (*self.conditions, condition) if condition else self.conditions
        return replace(self, variant=variant, conditions=conditions)


def flatten_spec(spec: ApiSpec) -> list[FieldNode]:
    return [node for endpoint in spec.endpoints for node in flatten_endpoint(spec.name, endpoint)]


def flatten_endpoint(api: str, endpoint: Endpoint) -> list[FieldNode]:
    if not endpoint.response_schema:
        return []
    fields: list[FieldNode] = []
    _walk(endpoint.response_schema, _Context(), api, endpoint.key, fields)
    return [_with_example(node, endpoint.response_examples, endpoint.response_sample_sources) for node in fields]


def merge_all_of(schema: dict[str, Any]) -> dict[str, Any]:
    if "allOf" not in schema:
        return schema
    merged = {key: value for key, value in schema.items() if key not in ("allOf", "properties", "required")}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for member in schema["allOf"]:
        if not isinstance(member, dict):
            continue
        member = merge_all_of(member)
        _merge_properties(properties, member.get("properties") or {})
        required.extend(member.get("required") or [])
        for key in ("type", "description", "discriminator", "items"):
            if key in member:
                merged.setdefault(key, member[key])
        # A named base's oneOf lists its subtypes, not content of this schema; following
        # it would re-enter the subtype hierarchy. Inline oneOf is genuine content.
        if SCHEMA_NAME_KEY not in member:
            for key in ("oneOf", "anyOf"):
                if key in member:
                    merged.setdefault(key, member[key])
    _merge_properties(properties, schema.get("properties") or {})
    required.extend(schema.get("required") or [])
    merged["properties"] = properties
    merged["required"] = list(dict.fromkeys(required))
    return merged


def schema_type(schema: dict[str, Any]) -> tuple[str, bool]:
    declared = schema.get("type")
    nullable = bool(schema.get("nullable"))
    if isinstance(declared, list):
        nullable = nullable or "null" in declared
        declared = next((t for t in declared if t != "null"), None)
    if declared:
        return str(declared), nullable
    if "properties" in schema or "additionalProperties" in schema:
        return "object", nullable
    if "items" in schema:
        return "array", nullable
    if "enum" in schema:
        return "string", nullable
    return "any", nullable


def _merge_properties(into: dict[str, Any], new: dict[str, Any]) -> None:
    for name, prop in new.items():
        existing = into.get(name)
        into[name] = {**existing, **prop} if isinstance(existing, dict) and isinstance(prop, dict) else prop


def _walk(schema: Any, ctx: _Context, api: str, endpoint: str, out: list[FieldNode]) -> None:
    if not isinstance(schema, dict) or ctx.depth > MAX_DEPTH or CYCLE_KEY in schema:
        return
    if UNRESOLVED_KEY in schema:
        out.append(_leaf(api, endpoint, ctx, {"description": f"unresolved {schema[UNRESOLVED_KEY]}"}, "any", False))
        return

    schema = merge_all_of(schema)
    kind, nullable = schema_type(schema)
    branches = schema.get("oneOf") or schema.get("anyOf")
    if branches or kind in ("object", "array"):
        ctx = ctx.named(schema.get(SCHEMA_NAME_KEY))
    if branches:
        for label, condition, branch in _variants(schema, branches):
            _walk(branch, ctx.in_variant(label, condition), api, endpoint, out)
        if not schema.get("properties"):
            return

    ctx = replace(ctx, nullable=ctx.nullable or nullable)
    if kind == "object":
        _walk_object(schema, ctx, api, endpoint, out)
    elif kind == "array":
        items = schema.get("items") or {}
        item_kind, _ = schema_type(merge_all_of(items)) if isinstance(items, dict) else ("any", False)
        if item_kind in ("object", "array") or (isinstance(items, dict) and (items.get("oneOf") or items.get("anyOf"))):
            _walk(items, ctx.array_items(), api, endpoint, out)
        else:
            out.append(_leaf(api, endpoint, ctx.array_items(), items, item_kind, False))
    elif ctx.path:
        out.append(_leaf(api, endpoint, ctx, schema, kind, False))


def _walk_object(schema: dict, ctx: _Context, api: str, endpoint: str, out: list[FieldNode]) -> None:
    required = set(schema.get("required") or [])
    for name, prop in (schema.get("properties") or {}).items():
        _walk(prop, ctx.child(str(name), name in required), api, endpoint, out)
    extra = schema.get("additionalProperties")
    if isinstance(extra, dict) and extra and not schema.get("properties"):
        _walk(extra, ctx.child(MAP_KEY_SEGMENT, False), api, endpoint, out)


def _variants(schema: dict, branches: list) -> list[tuple[str, tuple[str, str] | None, dict]]:
    discriminator = schema.get("discriminator") or {}
    property_name = discriminator.get("propertyName")
    value_by_schema = {
        str(ref).rsplit("/", 1)[-1]: value for value, ref in (discriminator.get("mapping") or {}).items()
    }
    variants = []
    for index, branch in enumerate(b for b in branches if isinstance(b, dict)):
        label = branch.get(SCHEMA_NAME_KEY) or branch.get("title") or f"option{index + 1}"
        value = value_by_schema.get(label) or _single_enum_value(merge_all_of(branch), property_name)
        condition = (property_name, value) if property_name and value else None
        variants.append((str(label), condition, branch))
    return variants


def _single_enum_value(branch: dict, property_name: str | None) -> str | None:
    prop = (branch.get("properties") or {}).get(property_name or "")
    if isinstance(prop, dict) and len(prop.get("enum") or []) == 1:
        return str(prop["enum"][0])
    return None


def _leaf(api: str, endpoint: str, ctx: _Context, schema: dict, kind: str, nullable: bool) -> FieldNode:
    example = schema.get("example")
    if example is None and isinstance(schema.get("examples"), list) and schema["examples"]:
        example = schema["examples"][0]
    return FieldNode(
        api=api,
        endpoint=endpoint,
        path=ctx.path,
        type=kind,
        required=ctx.required,
        nullable=ctx.nullable or nullable or bool(schema.get("nullable")),
        deprecated=bool(schema.get("deprecated")),
        format=schema.get("format"),
        enum=tuple(str(v) for v in schema.get("enum") or () if v is not None),
        description=str(schema.get("description") or "").strip(),
        example=example,
        variant=ctx.variant,
        condition=" and ".join(f"{prop} = {value}" for prop, value in ctx.conditions) or None,
        schema_names=ctx.schema_names,
        array_depth=ctx.array_depth,
    )


def _with_example(node: FieldNode, payloads: tuple[Any, ...], sources: tuple[str, ...] = ()) -> FieldNode:
    if not payloads:
        return node
    conditions = _parse_conditions(node.condition)
    values, documentation, used_sources = [], [], []
    for index, payload in enumerate(payloads):
        source = sources[index] if index < len(sources) else "inline example"
        documented = source != "inline example"
        found = _values_at(payload, node.path.split("."), conditions, strict=documented)
        values.extend(found)
        if documented and found:
            documentation.extend(found)
            used_sources.append(source)
    observed = tuple(dict.fromkeys(v for v in values if isinstance(v, str)))[:MAX_OBSERVED_VALUES]
    example = node.example if node.example is not None else next(iter(values), None)
    return replace(node, example=example, observed=observed, sample_sources=tuple(dict.fromkeys(used_sources)),
                   sample_context=describe_samples(documentation))


def _parse_conditions(condition: str | None) -> dict[str, str]:
    if not condition:
        return {}
    return dict(part.split(" = ", 1) for part in condition.split(" and "))


def _values_at(value: Any, segments: list[str], conditions: dict[str, str], strict: bool = False) -> list[Any]:
    if isinstance(value, dict):
        if any(str(value[k]) != expected for k, expected in conditions.items() if k in value):
            return []
        conditions = {k: expected for k, expected in conditions.items() if k not in value}
    if not segments:
        return [] if value is None or isinstance(value, (dict, list)) or (strict and conditions) else [value]
    head, rest = segments[0], segments[1:]
    is_array = head.endswith("[]")
    name = head.removesuffix("[]")
    if name:
        if not isinstance(value, dict) or name not in value:
            return []
        value = value[name]
    if not is_array:
        return _values_at(value, rest, conditions, strict)
    if not isinstance(value, list):
        return []
    found = []
    for item in value:
        if isinstance(item, dict) and any(str(item.get(k)) != v for k, v in conditions.items() if k in item):
            continue
        found.extend(_values_at(item, rest, conditions, strict))
    return found
