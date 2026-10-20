"""Domain vocabulary that turns raw identifier tokens into comparable concepts."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from api_mapper.loaders.document import load_document
from api_mapper.models.meaning import MeaningRule
from api_mapper.models.purpose import PurposeRule
from api_mapper.normalize.tokenizer import singularize, split_identifier

DEFAULT_LEXICON = Path(__file__).resolve().parents[3] / "lexicon" / "finance.yaml"
ENTITY_CONCEPT = "account"


@dataclass(frozen=True)
class Lexicon:
    abbreviations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    phrases: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = ()
    synonyms: dict[str, str] = field(default_factory=dict)
    related: dict[frozenset[str], float] = field(default_factory=dict)
    generic: frozenset[str] = frozenset()
    weak: frozenset[str] = frozenset()
    stopwords: frozenset[str] = frozenset()
    families: dict[str, str] = field(default_factory=dict)
    roles: frozenset[str] = frozenset()
    exclusive_modifiers: frozenset[str] = frozenset()
    defining_modifiers: frozenset[str] = frozenset()
    vocabulary: frozenset[str] = frozenset()
    minor_unit_markers: tuple[str, ...] = ()
    epoch_markers: tuple[str, ...] = ()
    meaning_rules: tuple[MeaningRule, ...] = ()
    purpose_rules: tuple[PurposeRule, ...] = ()

    @classmethod
    def load(cls, *paths: Path) -> "Lexicon":
        lexicon = cls()
        for path in paths or (DEFAULT_LEXICON,):
            lexicon = lexicon.merged_with(_parse(load_document(path)))
        return lexicon

    def merged_with(self, other: "Lexicon") -> "Lexicon":
        phrases = {source: target for source, target in (*self.phrases, *other.phrases)}
        return Lexicon(
            abbreviations={**self.abbreviations, **other.abbreviations},
            phrases=_longest_first(phrases.items()),
            synonyms={**self.synonyms, **other.synonyms},
            related={**self.related, **other.related},
            generic=self.generic | other.generic,
            weak=self.weak | other.weak,
            stopwords=self.stopwords | other.stopwords,
            families={**self.families, **other.families},
            roles=self.roles | other.roles,
            exclusive_modifiers=self.exclusive_modifiers | other.exclusive_modifiers,
            defining_modifiers=self.defining_modifiers | other.defining_modifiers,
            vocabulary=self.vocabulary | other.vocabulary,
            minor_unit_markers=(*self.minor_unit_markers, *other.minor_unit_markers),
            epoch_markers=(*self.epoch_markers, *other.epoch_markers),
            meaning_rules=tuple({(r.group, r.role): r for r in (*self.meaning_rules, *other.meaning_rules)}.values()),
            purpose_rules=tuple({(r.group, r.role): r for r in (*self.purpose_rules, *other.purpose_rules)}.values()),
        )

    def concepts(self, text: str) -> tuple[str, ...]:
        return self.concepts_of_tokens(split_identifier(text))

    def concepts_of_tokens(self, tokens: Iterable[str]) -> tuple[str, ...]:
        words = [expanded for token in tokens for expanded in self._expand(token)]
        words = self._apply_phrases(words)
        concepts = [self.synonyms.get(word, word) for word in words if word not in self.stopwords]
        return tuple(dict.fromkeys(c for c in concepts if c))

    def relatedness(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        return self.related.get(frozenset((a, b)), 0.0)

    def related_to(self, concept: str) -> tuple[str, ...]:
        return self._related_index.get(concept, ())

    @cached_property
    def known_words(self) -> frozenset[str]:
        """Every plain word the lexicon understands, used to read unknown spellings."""
        words = set(self.synonyms) | set(self.families) | set(self.synonyms.values()) | self.vocabulary
        words |= {w for expansion in self.abbreviations.values() for w in expansion}
        words |= {w for source, target in self.phrases for w in (*source, *target)}
        words |= {w for pair in self.related for w in pair}
        words |= self.roles | self.generic | self.weak | self.exclusive_modifiers
        return frozenset(words)

    @cached_property
    def _compound_parts(self) -> frozenset[str]:
        return self.vocabulary | frozenset(self.synonyms) | frozenset(self.families) | self.stopwords

    @cached_property
    def _related_index(self) -> dict[str, tuple[str, ...]]:
        index: dict[str, list[str]] = {}
        for pair in self.related:
            a, b = sorted(pair)
            index.setdefault(a, []).append(b)
            index.setdefault(b, []).append(a)
        return {concept: tuple(sorted(others)) for concept, others in index.items()}

    def is_known(self, token: str) -> bool:
        """True when the lexicon defines this word, so loose spelling guesses must not reinterpret it."""
        word = singularize(token.lower())
        return any(w in self.abbreviations or w in self.synonyms for w in (token.lower(), word))

    def split_compound(self, word: str) -> tuple[str, ...]:
        """`creditcard` -> (credit, card) when every part is a known word; otherwise the word itself."""
        known = self._compound_parts
        best: list[tuple[str, ...] | None] = [()] + [None] * len(word)
        for end in range(1, len(word) + 1):
            for start in range(end):
                part = word[start:end]
                if best[start] is not None and part in known and len(part) >= 2:
                    option = (*best[start], part)
                    if best[end] is None or len(option) < len(best[end]):
                        best[end] = option
        return best[len(word)] if best[len(word)] and len(best[len(word)]) > 1 else (word,)

    def family_of(self, concepts: Iterable[str]) -> frozenset[str]:
        return frozenset(self.families[c] for c in concepts if c in self.families)

    def roles_of(self, concepts: Iterable[str]) -> frozenset[str]:
        return frozenset(c for c in concepts if c in self.roles)

    def is_generic(self, concepts: Iterable[str]) -> bool:
        concepts = tuple(concepts)
        return not concepts or all(c in self.generic for c in concepts)

    def mentions_any(self, text: str, markers: Iterable[str]) -> bool:
        lowered = text.lower()
        return any(re.search(rf"\b{re.escape(marker)}\b", lowered) for marker in markers)

    def _expand(self, token: str) -> tuple[str, ...]:
        if token in self.abbreviations:
            return self.abbreviations[token]
        single = singularize(token)
        return self.abbreviations.get(single, (single,))

    @cached_property
    def _phrases_by_first_word(self) -> dict[str, tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]]:
        index: dict[str, list] = {}
        for source, target in self.phrases:
            index.setdefault(source[0], []).append((source, target))
        return {word: tuple(phrases) for word, phrases in index.items()}

    def _apply_phrases(self, words: list[str]) -> list[str]:
        result: list[str] = []
        index = 0
        while index < len(words):
            for source, target in self._phrases_by_first_word.get(words[index], ()):
                if tuple(words[index : index + len(source)]) == source:
                    result.extend(target)
                    index += len(source)
                    break
            else:
                result.append(words[index])
                index += 1
        return result


def _parse(raw: dict) -> Lexicon:
    raw = raw or {}
    synonyms = {
        _normal(word): concept for concept, words in (raw.get("synonyms") or {}).items() for word in [concept, *words]
    }
    families = {
        synonyms.get(_normal(word), _normal(word)): family
        for family, words in (raw.get("qualifier_families") or {}).items()
        for word in [family, *words]
    }
    return Lexicon(
        abbreviations={_normal(k): tuple(str(v).lower().split()) for k, v in (raw.get("abbreviations") or {}).items()},
        phrases=_longest_first(
            (tuple(str(source).lower().split()), tuple(str(target).lower().split()))
            for source, target in raw.get("phrases") or []
        ),
        synonyms=synonyms,
        related={frozenset((str(a), str(b))): float(score) for a, b, score in raw.get("related") or []},
        generic=frozenset(raw.get("generic") or ()),
        weak=frozenset(raw.get("weak") or ()),
        stopwords=frozenset(_normal(w) for w in raw.get("stopwords") or ()),
        families=families,
        roles=frozenset(synonyms.get(_normal(w), _normal(w)) for w in raw.get("role_markers") or ()),
        exclusive_modifiers=frozenset(
            synonyms.get(_normal(w), _normal(w)) for w in raw.get("exclusive_modifiers") or ()
        ),
        defining_modifiers=frozenset(synonyms.get(_normal(w), _normal(w)) for w in raw.get("defining_modifiers") or ()),
        vocabulary=frozenset(str(w).lower() for w in raw.get("vocabulary") or ()),
        minor_unit_markers=tuple(str(m).lower() for m in raw.get("minor_unit_markers") or ()),
        epoch_markers=tuple(str(m).lower() for m in raw.get("epoch_markers") or ()),
        meaning_rules=tuple(
            MeaningRule(
                group=str(r["group"]),
                role=str(r["role"]),
                concepts=frozenset(r["concepts"]),
                name_phrases=tuple(r.get("name_phrases") or ()),
                definition_phrases=tuple(r.get("definition_phrases") or ()),
                require_source=bool(r.get("require_source", False)),
                name_concepts=frozenset(r.get("name_concepts") or ()),
            )
            for r in raw.get("meaning_rules") or ()
        ),
        purpose_rules=tuple(_purpose_rule(r) for r in raw.get("purpose_rules") or ()),
    )


def _purpose_rule(raw: dict) -> PurposeRule:
    patterns = raw.get("patterns")
    if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p for p in patterns):
        raise ValueError("purpose rule patterns must be a non-empty list of regular expressions")
    for pattern in patterns:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as error:
            raise ValueError(f"invalid purpose rule pattern: {error}") from error
    return PurposeRule(
        str(raw["group"]),
        str(raw["role"]),
        str(raw["label"]),
        tuple(patterns),
        bool(raw.get("expects_labels", False)),
        bool(raw.get("match_names", False)),
    )


def _normal(word: str) -> str:
    return singularize(str(word).lower())


def _longest_first(pairs: Iterable[tuple[tuple[str, ...], tuple[str, ...]]]) -> tuple:
    return tuple(sorted(pairs, key=lambda pair: (-len(pair[0]), pair[0])))
