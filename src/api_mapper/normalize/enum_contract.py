"""Read explicit value lists and quoted aliases; schema enums always take precedence."""

import re
from collections import defaultdict
from functools import lru_cache

from api_mapper.models import FieldNode
from api_mapper.models.enum_contract import EnumContract
from api_mapper.models.purpose import ContextClue

_LIST = re.compile(r'\b(?:allowed values|possible values|enum values|one of)\s*:\s*([^\n.;]+)', re.IGNORECASE)
_ALIAS = re.compile(r'["`\']([^"`\'\n]+)["`\']\s*(?:->|→|maps to)\s*["`\']([^"`\'\n]+)["`\']', re.IGNORECASE)
_VALUE = re.compile(r'[\w -]{1,100}')


def enum_contract(node: FieldNode, alias_outputs: tuple[str, ...] | None = None) -> EnumContract:
    return _contract(node.enum, node.description, node.documentation, alias_outputs)


@lru_cache(maxsize=10_000)
def _contract(declared: tuple[str, ...], description: str, documentation: tuple[ContextClue, ...], alias_outputs: tuple[str, ...] | None) -> EnumContract:
    passages = [(description, 'schema description')]
    passages.extend((clue.text, clue.location) for clue in documentation)
    declarations, citations, warnings = [], [], []
    pairs: dict[str, set[str]] = defaultdict(set)
    for text, location in passages:
        for match in _LIST.finditer(text):
            values = _values(match[1])
            if values:
                declarations.append(values)
                citations.append(location)
        for source, target in _ALIAS.findall(text):
            pairs[source].add(target)
            citations.append(location)
    values, origin = declared, 'specification' if declared else ''
    if declared:
        if any(set(documented) != set(declared) for documented in declarations):
            warnings.append('Documentation disagrees with the specification; specification values take precedence.')
    elif declarations:
        if all(set(declared) == set(declarations[0]) for declared in declarations):
            values, origin = declarations[0], 'documentation'
        else:
            warnings.append('Conflicting documented value lists; no allowed set was inferred.')
    aliases, unresolved = {}, []
    allowed_aliases = values if alias_outputs is None else alias_outputs
    for source, targets in pairs.items():
        if len(targets) != 1:
            unresolved.append(source)
            warnings.append(f'Conflicting documented translations for {source!r}; choose explicitly.')
        elif (target := next(iter(targets))) in allowed_aliases:
            aliases[source] = target
        elif allowed_aliases:
            unresolved.append(source)
            warnings.append(f'Documented translation for {source!r} uses disallowed output {target!r}.')
    return EnumContract(values, origin, tuple(dict.fromkeys(citations)), aliases, tuple(warnings), tuple(unresolved))


def _values(text: str) -> tuple[str, ...]:
    text = text.strip().removeprefix('[').removesuffix(']')
    raw = [part.strip() for part in re.split(r'\s*[,|]\s*', text)]
    if any(not ((part[:1] in {'"', "'", '`'} and part[-1:] == part[:1]) or re.fullmatch(r'[A-Z0-9_\-]+', part)) for part in raw):
        return ()
    parts = [part.strip('"\'`').strip() for part in raw]
    if not parts or len(parts) > 100 or any(not _VALUE.fullmatch(part) for part in parts):
        return ()
    return tuple(dict.fromkeys(parts))
