"""Read explicit definitions conservatively; unknown or conditional purposes stay unknown."""

import re
from functools import lru_cache

from api_mapper.models.field_node import FieldNode
from api_mapper.models.purpose import ContextClue, PurposeFact, PurposeRule
from api_mapper.normalize.definitions import leading_definition


def field_purposes(node: FieldNode, rules: tuple[PurposeRule, ...]) -> tuple[PurposeFact, ...]:
    clues = (ContextClue(node.description, f"schema:{node.path}.description"), *node.context_clues, *node.documentation)
    return tuple(
        PurposeFact(rule.group, rule.role, rule.label, clue.location, definition)
        for clue in clues
        if (definition := _affirmative(clue.text))
        for rule in rules
        if any(_pattern(p).search(definition) for p in rule.patterns)
    )


def _affirmative(text: str) -> str:
    definition = leading_definition(text)
    definition = re.split(
        r"\b(?:not|never|no|without|lacks|cannot|rather than|instead of|unlike|excluding|doesn't|isn't)\b",
        definition,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    if re.search(r"\b(?:may|might|could|whether|if|example)\b", definition, flags=re.IGNORECASE):
        return ""
    return definition.strip(" ,;:-")


@lru_cache(maxsize=256)
def _pattern(pattern: str):
    return re.compile(pattern, re.IGNORECASE)
