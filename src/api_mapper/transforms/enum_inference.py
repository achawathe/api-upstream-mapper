"""Suggest value translations by comparing each API's own contract and definitions."""

from api_mapper.models import FieldNode, TransformKind, TransformStep
from api_mapper.normalize.enum_contract import enum_contract
from api_mapper.transforms.enum_definition_matching import compare_value_definitions
from api_mapper.transforms.enum_mapping import EnumMapper, EnumMapping


def enum_transform(target: FieldNode, source: FieldNode, mapper: EnumMapper) -> tuple[TransformStep | None, EnumMapping | None]:
    contract = enum_contract(target)
    source_contract = enum_contract(source)
    source_values = source.enum or source_contract.values or source.observed or ((source.example,) if isinstance(source.example, str) else ())
    if not contract.values:
        return None, None
    preliminary = mapper.map(source_values, contract.values)
    enum_mapping = compare_value_definitions(preliminary, source_contract, contract)
    uses_context = enum_mapping != preliminary or target.documentation or source.documentation or 'documentation' in (contract.origin, source_contract.origin)
    citations = list(dict.fromkeys((*contract.citations, *source_contract.citations))) if uses_context else []
    if source.enum and all(enum_mapping.mapping.get(value) == value for value in source.enum) and contract.origin == 'specification' and not citations:
        return None, enum_mapping
    mapping = enum_mapping.mapping if source_values else {value: value for value in contract.values}
    inferred = "" if source.enum else " (source strings are not schema-enumerated; unlisted strings fail)"
    step = TransformStep(
        kind=TransformKind.ENUM_MAP,
        description=_describe_enum(enum_mapping) + inferred,
        params={"mapping": mapping, "unmapped": list(enum_mapping.unmapped), "from_samples": not source.enum,
                "target_origin": contract.origin, "rule_by_value": enum_mapping.rule_by_value,
                "citations": citations, "open_source": not source_values},
    )
    return step, enum_mapping if source_values else None


def _describe_enum(mapping: EnumMapping) -> str:
    pairs = ", ".join(f"{s}->{t}" for s, t in mapping.mapping.items() if s != t)
    unmapped = f"; no match for {', '.join(mapping.unmapped)}" if mapping.unmapped else ""
    return f"map values {pairs or '(identical)'}{unmapped}"
