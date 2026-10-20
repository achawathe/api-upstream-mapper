"""Extract descriptions of an API's own values without reading mapping instructions."""

import re

from api_mapper.models.purpose import ContextClue


def value_definitions(values: tuple[str, ...], passages: list[tuple[str, str]]) -> dict[str, tuple[ContextClue, ...]]:
    definitions = {}
    for value in values:
        pattern = re.compile(
            r"""(?<![\w])["'`]?""" + re.escape(value)
            + r"""["'`]?(?![\w])\s*(?:means|denotes|represents|indicates|:)\s+([^.;\n]+)""",
            re.IGNORECASE,
        )
        clues = [ContextClue(match[1].strip(), location) for text, location in passages
                 for match in pattern.finditer(text)]
        if clues:
            definitions[value] = tuple(dict.fromkeys(clues))
    return definitions
