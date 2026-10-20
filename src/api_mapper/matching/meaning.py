"""Explicit domain distinctions constrain both rules and NLP; unknown meanings stay unknown."""

from api_mapper.models import FieldProfile
from api_mapper.models.meaning import MeaningRule
from api_mapper.normalize.definitions import leading_definition
from api_mapper.normalize.tokenizer import split_identifier


class MeaningMatcher:
    def __init__(self, rules: tuple[MeaningRule, ...]):
        self.rules = rules
        self._cache: dict[tuple, dict[str, frozenset[str]]] = {}

    def conflicts(self, target: FieldProfile, source: FieldProfile) -> list[str]:
        left, right = self._roles(target), self._roles(source)
        return [f"{group}: {'/'.join(sorted(left[group]))} differs from {'/'.join(sorted(right[group]))}"
                for group in sorted(left.keys() & right.keys()) if left[group].isdisjoint(right[group])]

    def unmet_requirements(self, target: FieldProfile, source: FieldProfile) -> list[str]:
        left, right = self._roles(target), self._roles(source)
        return [f"{rule.group}: target requires {rule.role}; source name and definition do not establish that role"
                for rule in self.rules if rule.require_source and left.get(rule.group) == {rule.role}
                and right.get(rule.group) != {rule.role}]

    def _roles(self, profile: FieldProfile) -> dict[str, frozenset[str]]:
        key = (profile.node.name, (profile.node.description, *(c.text for c in profile.node.documentation)), profile.leaf, profile.parent)
        if key not in self._cache:
            if len(self._cache) >= 4096:
                self._cache.clear()
            self._cache[key] = self._read(*key)
        return self._cache[key]

    def _read(self, name: str, descriptions: tuple[str, ...], concepts: tuple[str, ...], parent: tuple[str, ...]) -> dict[str, frozenset[str]]:
        words = " ".join(split_identifier(name))
        definitions = [" ".join(split_identifier(leading_definition(description))) for description in descriptions]
        named, described = {}, {}
        for rule in self.rules:
            if not rule.concepts.intersection(concepts):
                continue
            if _mentions(words, rule.name_phrases) or (rule.name_concepts and rule.name_concepts <= {*concepts, *parent}):
                named.setdefault(rule.group, set()).add(rule.role)
            if any(_mentions(definition, rule.definition_phrases) for definition in definitions):
                described.setdefault(rule.group, set()).add(rule.role)
        return {group: frozenset(named.get(group) or described[group]) for group in named.keys() | described.keys()}


def _mentions(text: str, phrases: tuple[str, ...]) -> bool:
    return any(f" {phrase} " in f" {text} " for phrase in phrases)
