"""Compare independently documented meanings; ambiguous or differing definitions need review."""

import re

from api_mapper.models.enum_contract import EnumContract
from api_mapper.transforms.enum_mapping import EnumMapping


def compare_value_definitions(mapping: EnumMapping, source: EnumContract, target: EnumContract) -> EnumMapping:
    result, rules = dict(mapping.mapping), dict(mapping.rule_by_value)
    unmapped = list(mapping.unmapped)
    for value in (*mapping.mapping, *mapping.unmapped):
        meanings = _meanings(source, value)
        if not meanings:
            continue
        hits = [output for output in target.values if meanings == _meanings(target, output) and len(meanings) == 1]
        if len(hits) == 1:
            result[value], rules[value] = hits[0], 'matching API value definitions'
            unmapped = [item for item in unmapped if item != value]
        elif hits or len(meanings) > 1 or (value in result and _meanings(target, result[value])):
            result.pop(value, None)
            rules.pop(value, None)
            if value not in unmapped:
                unmapped.append(value)
    return EnumMapping(result, rules, tuple(unmapped))


def _meanings(contract: EnumContract, value: str) -> set[str]:
    return {' '.join(re.findall(r'\w+', clue.text.casefold())) for clue in contract.definitions.get(value, ())}
