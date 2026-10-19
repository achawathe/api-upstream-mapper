"""Concept-bag similarity: a weighted Dice coefficient with partial credit for related concepts."""

import math
from collections import Counter
from collections.abc import Iterable

from api_mapper.models import FieldProfile
from api_mapper.normalize.lexicon import ENTITY_CONCEPT, Lexicon

WEAK_CONCEPT_FACTOR = 0.3


class ConceptWeights:
    """Rare concepts say more than common ones: `escrow` matters more than `identifier`."""

    def __init__(self, profiles: Iterable[FieldProfile], lexicon: Lexicon):
        bags = [profile.bag for profile in profiles]
        document_frequency = Counter(concept for bag in bags for concept in bag)
        total = len(bags)
        self._weights = {
            concept: (math.log((total + 1) / (count + 1)) + 1.0) * (WEAK_CONCEPT_FACTOR if concept in lexicon.weak else 1.0)
            for concept, count in document_frequency.items()
        }
        self._default = math.log(total + 1) + 1.0

    def __call__(self, concept: str) -> float:
        return self._weights.get(concept, self._default)


def bag_similarity(
    a: dict[str, float], b: dict[str, float], weight: ConceptWeights, lexicon: Lexicon
) -> tuple[float, list[tuple[str, str, float]]]:
    weighted_a = {concept: share * weight(concept) for concept, share in a.items()}
    weighted_b = {concept: share * weight(concept) for concept, share in b.items()}
    total = sum(weighted_a.values()) + sum(weighted_b.values())
    if total == 0:
        return 0.0, []

    pairs = sorted(
        ((lexicon.relatedness(x, y), x, y) for x in a for y in b if lexicon.relatedness(x, y) > 0),
        key=lambda pair: (-pair[0], pair[1], pair[2]),
    )
    used_a: set[str] = set()
    used_b: set[str] = set()
    matched = 0.0
    alignment = []
    for relatedness, x, y in pairs:
        if x in used_a or y in used_b:
            continue
        used_a.add(x)
        used_b.add(y)
        matched += relatedness * (weighted_a[x] + weighted_b[y])
        alignment.append((x, y, relatedness))
    return matched / total, alignment


def align_qualifier_words(
    bag: dict[str, float], other_bag: dict[str, float], other_families: frozenset[str], lexicon: Lexicon
) -> dict[str, float]:
    """In a loan API `loan_id` is the account id, and `debitAccount.id` is just the account id.

    A qualifier word whose family the other side already implies is judged by the
    qualifier signal, so it is removed from the name; if it stood in for the entity
    (`loan` in `loan_id`), it becomes `account`.
    """
    aligned = dict(bag)
    for concept in bag:
        family = lexicon.families.get(concept)
        if family is None or concept in other_bag or family not in other_families:
            continue
        share = aligned.pop(concept)
        if ENTITY_CONCEPT in other_bag and ENTITY_CONCEPT not in aligned:
            aligned[ENTITY_CONCEPT] = share
    return aligned
