"""Evidence for a numeric value encoded as text, independent of the API's business domain."""

import re

from api_mapper.models import FieldNode
from api_mapper.normalize.definitions import leading_definition

_NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")
_ENCODING = re.compile(
    r"\b(?:numeric string|string containing (?:an? )?(?:integer|number)|(?:integer|number|numeric value) (?:encoded|represented|serialized|stored|returned) as (?:a )?string)\b",
    re.IGNORECASE,
)


def has_numeric_text(source: FieldNode, integer: bool = False) -> bool:
    values = (*source.observed, *(() if source.example is None else (source.example,)))
    if values:
        return all(isinstance(v, str) and _NUMERIC.fullmatch(v) and (not integer or "." not in v) for v in values)
    definitions = (source.description, *(c.text for c in source.documentation))
    return any(
        _ENCODING.search(leading_definition(text))
        and not re.search(r"\b(?:not|never|may|might)\b", leading_definition(text), re.IGNORECASE)
        for text in definitions
    )
