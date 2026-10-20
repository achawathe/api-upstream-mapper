"""Build a channel value translation from declared sets, examples and cited aliases."""

from api_mapper.models import FieldNode, TransformKind, TransformStep
from api_mapper.normalize.enum_contract import enum_contract
from api_mapper.transforms.enum_mapping import EnumMapper, EnumMapping


def enum_transform(target: FieldNode, source: FieldNode, mapper: EnumMapper) -> tuple[TransformStep | None, EnumMapping | None]:
    contract = enum_contract(target)
    source_contract = enum_contract(source)
    source_values = source.enum or source_contract.values or source.observed or ((source.example,) if isinstance(source.example, str) else ())
    if not contract.values:
        return None, None
    enum_mapping = mapper.map(source_values, contract.values)
    source_translations = enum_contract(source, contract.values)
    conflicts = {value for value in contract.aliases.keys() & source_translations.aliases.keys()
                 if contract.aliases[value] != source_translations.aliases[value]}
    conflicts.update((*contract.unresolved_aliases, *source_translations.unresolved_aliases))
    aliases = {value: output for value, output in {**source_translations.aliases, **contract.aliases}.items() if value not in conflicts}
    if conflicts:
        enum_mapping = EnumMapping({value: output for value, output in enum_mapping.mapping.items() if value not in conflicts},
                                   {value: rule for value, rule in enum_mapping.rule_by_value.items() if value not in conflicts},
                                   tuple(dict.fromkeys((*enum_mapping.unmapped, *(value for value in source_values if value in conflicts)))))
    if aliases:
        supported = {value: aliases[value] for value in source_values if value in aliases}
        mapping = {**enum_mapping.mapping, **supported}
        enum_mapping = EnumMapping(mapping, {**enum_mapping.rule_by_value, **dict.fromkeys(supported, 'documented alias')},
                                   tuple(value for value in enum_mapping.unmapped if value not in aliases))
    if source.enum and set(source.enum) <= set(contract.values) and contract.origin == 'specification' and not aliases and not conflicts:
        return None, enum_mapping
    mapping = {**enum_mapping.mapping, **aliases}
    if not source_values:
        mapping = {**{value: value for value in contract.values if value not in conflicts}, **aliases}
    inferred = "" if source.enum else " (source strings are not schema-enumerated; unlisted strings fail)"
    step = TransformStep(
        kind=TransformKind.ENUM_MAP,
        description=_describe_enum(enum_mapping) + inferred,
        params={"mapping": mapping, "unmapped": list(dict.fromkeys((*enum_mapping.unmapped, *sorted(conflicts)))), "from_samples": not source.enum,
                "target_origin": contract.origin, "rule_by_value": enum_mapping.rule_by_value,
                "citations": list(dict.fromkeys((*contract.citations, *source_translations.citations))), "open_source": not source_values,
                "translation_warnings": [f'Documented translation for {value!r} is unresolved; choose its output explicitly.' for value in sorted(conflicts)]},
    )
    return step, enum_mapping if source_values else None


def _describe_enum(mapping: EnumMapping) -> str:
    pairs = ", ".join(f"{s}->{t}" for s, t in mapping.mapping.items() if s != t)
    unmapped = f"; no match for {', '.join(mapping.unmapped)}" if mapping.unmapped else ""
    return f"map values {pairs or '(identical)'}{unmapped}"
