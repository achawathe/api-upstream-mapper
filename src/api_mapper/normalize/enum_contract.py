"""Read an API field's own allowed values and definitions; schema enums always take precedence."""

import re
from functools import lru_cache

from api_mapper.models import FieldNode
from api_mapper.models.enum_contract import EnumContract
from api_mapper.models.purpose import ContextClue
from api_mapper.normalize.enum_definitions import value_definitions

_LIST = re.compile(r"\b(?:allowed values|possible values|enum values|one of)\s*:\s*([^\n.;]+)", re.IGNORECASE)
_VALUE = re.compile(r"[\w -]{1,100}")


def enum_contract(node: FieldNode) -> EnumContract:
    examples = node.observed + ((node.example,) if isinstance(node.example, str) else ())
    return _contract(node.enum, node.description, node.documentation, examples)


@lru_cache(maxsize=10_000)
def _contract(
    declared: tuple[str, ...], description: str, documentation: tuple[ContextClue, ...], examples: tuple[str, ...]
) -> EnumContract:
    passages = [(description, "schema description")]
    passages.extend((clue.text, clue.location) for clue in documentation)
    declarations, citations, warnings = [], [], []
    for text, location in passages:
        for match in _LIST.finditer(text):
            values = _values(match[1])
            if values:
                declarations.append(values)
                citations.append(location)
    values, origin = declared, "specification" if declared else ""
    if declared:
        if any(set(documented) != set(declared) for documented in declarations):
            warnings.append("Documentation disagrees with the specification; specification values take precedence.")
    elif declarations:
        if all(set(declared) == set(declarations[0]) for declared in declarations):
            values, origin = declarations[0], "documentation"
        else:
            warnings.append("Conflicting documented value lists; no allowed set was inferred.")
    definitions = value_definitions(tuple(dict.fromkeys((*values, *examples))), passages)
    citations.extend(clue.location for clues in definitions.values() for clue in clues)
    return EnumContract(values, origin, tuple(dict.fromkeys(citations)), definitions, tuple(warnings))


def _values(text: str) -> tuple[str, ...]:
    text = text.strip().removeprefix("[").removesuffix("]")
    raw = [part.strip() for part in re.split(r"\s*[,|]\s*", text)]
    if any(
        not ((part[:1] in {'"', "'", "`"} and part[-1:] == part[:1]) or re.fullmatch(r"[A-Z0-9_\-]+", part))
        for part in raw
    ):
        return ()
    parts = [part.strip("\"'`").strip() for part in raw]
    if not parts or len(parts) > 100 or any(not _VALUE.fullmatch(part) for part in parts):
        return ()
    return tuple(dict.fromkeys(parts))
