"""Narrows the sources worth scoring for a target, so large API sets stay fast.

A source is a candidate when it shares a concept (or a related concept) with the
target, or when the names are spelled almost alike (catches unknown abbreviations).
"""

from rapidfuzz import fuzz, process

from api_mapper.matching.purpose import has_labels, roles
from api_mapper.matching.semantic import SemanticIndex
from api_mapper.models import FieldProfile
from api_mapper.normalize.lexicon import Lexicon

MIN_INDEXED_SHARE = 0.5
SPELLING_CUTOFF = 80


class CandidateIndex:
    def __init__(self, sources: list[FieldProfile], lexicon: Lexicon, semantic: SemanticIndex | None = None):
        self.sources = sources
        self.semantic = semantic
        self.lexicon = lexicon
        self._by_concept: dict[str, set[int]] = {}
        for index, source in enumerate(sources):
            for concept, share in source.bag.items():
                if share >= MIN_INDEXED_SHARE:
                    self._by_concept.setdefault(concept, set()).add(index)
        self._compact_names = [source.compact_leaf for source in sources]
        self._by_purpose: dict[tuple[str, str], set[int]] = {}
        self._labels = set()
        for index, source in enumerate(sources):
            for group, values in roles(source).items():
                if len(values) == 1:
                    self._by_purpose.setdefault((group, next(iter(values))), set()).add(index)
            if has_labels(source):
                self._labels.add(index)

    def candidates_for(self, target: FieldProfile) -> list[FieldProfile]:
        indexes: set[int] = set()
        for group, values in roles(target).items():
            if group != "origin" and len(values) == 1:
                indexes |= self._by_purpose.get((group, next(iter(values))), set())
        if any(fact.expects_labels for fact in target.purposes):
            indexes |= self._labels
        for concept, share in target.bag.items():
            if share < MIN_INDEXED_SHARE:
                continue
            for related in (concept, *self.lexicon.related_to(concept)):
                indexes |= self._by_concept.get(related, set())
        if target.compact_leaf:
            for _, _, index in process.extract(
                target.compact_leaf, self._compact_names, scorer=fuzz.ratio, score_cutoff=SPELLING_CUTOFF, limit=None
            ):
                indexes.add(index)
        found = {self.sources[i].node.key: self.sources[i] for i in sorted(indexes)}
        if self.semantic:
            for source in self.semantic.candidates_for(target, self.sources):
                found[source.node.key] = source
        return list(found.values())
