"""Read explicit definitions conservatively; unknown or conditional purposes stay unknown."""

import re
from functools import lru_cache

from api_mapper.models.field_node import FieldNode
from api_mapper.models.purpose import ContextClue, PurposeFact, PurposeRule
from api_mapper.normalize.definitions import leading_definition
from api_mapper.normalize.tokenizer import split_identifier


def field_purposes(node: FieldNode, rules: tuple[PurposeRule, ...]) -> tuple[PurposeFact, ...]:
    clues = (ContextClue(node.description, f"schema:{node.path}.description"), *node.context_clues, *node.documentation)
    name = ContextClue(" ".join(split_identifier(node.name)), f"name:{node.path}")
    return tuple(
        PurposeFact(rule.group, rule.role, rule.label, clue.location, definition, rule.expects_labels)
        for clue in (*clues, name)
        if (definition := _affirmative(clue.text))
        for rule in rules
        if (clue is not name or rule.match_names) and any(_pattern(p).search(definition) for p in rule.patterns)
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
