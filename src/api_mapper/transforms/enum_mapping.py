"""Maps each source enum value to at most one target enum value.

An exact match (ignoring case and separators) is tried first; then rules run from strictest to loosest and a looser rule only applies when it picks a
single target; ambiguous values stay unmapped rather than guessed.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache, lru_cache

from api_mapper.normalize.lexicon import Lexicon
from api_mapper.normalize.tokenizer import split_identifier

CACHE_SIZE = 100_000


@dataclass(frozen=True)
class EnumMapping:
    mapping: dict[str, str]
    rule_by_value: dict[str, str]
    unmapped: tuple[str, ...]

    @property
    def source_coverage(self) -> float:
        total = len(self.mapping) + len(self.unmapped)
        return len(self.mapping) / total if total else 0.0

    def target_coverage(self, target_count: int) -> float:
        return len(set(self.mapping.values())) / target_count if target_count else 0.0


class EnumMapper:
    def __init__(self, lexicon: Lexicon):
        self._rules = _rules(lexicon)
        self._cache: dict[tuple[tuple[str, ...], tuple[str, ...]], EnumMapping] = {}

    def map(self, sources: Sequence[str], targets: Sequence[str]) -> EnumMapping:
        key = (tuple(sources), tuple(targets))
        if key not in self._cache:
            self._cache[key] = self._map(key[0], key[1])
        return self._cache[key]

    def _map(self, sources: tuple[str, ...], targets: tuple[str, ...]) -> EnumMapping:
        exact: dict[str, list[str]] = {}
        for target in targets:
            exact.setdefault(_compact(target), []).append(target)
        mapping: dict[str, str] = {}
        rule_by_value: dict[str, str] = {}
        unmapped: list[str] = []
        for source in sources:
            same = exact.get(_compact(source), [])
            if len(same) == 1:
                mapping[source], rule_by_value[source] = same[0], "exact"
                continue
            for rule_name, matches in self._rules:
                hits = [t for t in targets if matches(source, t)]
                if len(hits) == 1:
                    mapping[source] = hits[0]
                    rule_by_value[source] = rule_name
                    break
            else:
                unmapped.append(source)
        return EnumMapping(mapping=mapping, rule_by_value=rule_by_value, unmapped=tuple(unmapped))


def map_enum_values(sources: Sequence[str], targets: Sequence[str], lexicon: Lexicon) -> EnumMapping:
    return EnumMapper(lexicon).map(sources, targets)


def _rules(lexicon: Lexicon) -> list[tuple[str, Callable[[str, str], bool]]]:
    @cache
    def words(value: str) -> tuple[str, ...]:
        return tuple(part for w in _words(value) for part in lexicon.split_compound(w))

    @cache
    def concepts(value: str) -> frozenset[str]:
        return frozenset(lexicon.concepts_of_tokens(words(value)))

    @cache
    def defined(value: str) -> bool:
        return any(lexicon.is_known(w) for w in _words(value))

    def same_concepts(source: str, target: str) -> bool:
        return bool(concepts(source)) and concepts(source) == concepts(target)

    def unknown(rule: Callable[[str, str], bool]) -> Callable[[str, str], bool]:
        """Loose spelling rules never reinterpret a value the lexicon defines: CC is a credit card, not CHECKING."""
        return lambda s, t: not defined(s) and rule(s, t)

    return [
        ("synonym", same_concepts),
        ("token", lambda s, t: _compact(s) in _words(t) and len(_words(t)) > 1),
        ("initials", unknown(lambda s, t: len(words(t)) > 1 and _compact(s) == "".join(w[0] for w in words(t)))),
        ("prefix", unknown(_is_prefix_pair)),
        ("abbreviation", unknown(_is_abbreviation)),
        ("initial-letter", unknown(lambda s, t: len(_compact(s)) == 1 and _compact(t).startswith(_compact(s)))),
    ]


@lru_cache(maxsize=CACHE_SIZE)
def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


@lru_cache(maxsize=CACHE_SIZE)
def _words(value: str) -> tuple[str, ...]:
    return tuple(w for part in re.split(r"[^A-Za-z0-9]+", value) for w in split_identifier(part.lower()))


def _is_prefix_pair(source: str, target: str) -> bool:
    s, t = _compact(source), _compact(target)
    return (len(s) >= 2 and t.startswith(s)) or (len(t) >= 3 and s.startswith(t))


def _is_abbreviation(source: str, target: str) -> bool:
    """CHK -> CHECKING, MMA -> MONEYMARKET: source letters appear in order, starting at the same letter."""
    s, t = _compact(source), _compact(target)
    if len(s) < 3 or not t.startswith(s[0]):
        return False
    position = 0
    for char in s:
        position = t.find(char, position)
        if position < 0:
            return False
        position += 1
    return True
