"""Turns scored candidates into a decision per target field.

auto     best candidate is confident and clearly ahead of any different alternative
review   plausible but uncertain, ambiguous, or its source is claimed by a stronger target
unmapped nothing plausible
derived  the field is the discriminator of its own variant, so its value is fixed
"""

from dataclasses import dataclass

from api_mapper.matching.review import review_reasons, semantic_fallback
from api_mapper.models import (
    Candidate,
    FieldMapping,
    FieldNode,
    FieldProfile,
    MappingStatus,
)


@dataclass(frozen=True)
class Thresholds:
    auto: float = 0.72
    review: float = 0.50
    ambiguity_margin: float = 0.03
    alternatives_kept: int = 5


DEFAULT_THRESHOLDS = Thresholds()


def assign(
    targets: list[FieldProfile],
    candidates_by_target: dict[str, list[Candidate]],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> list[FieldMapping]:
    mappings = [_decide(target, candidates_by_target.get(target.node.key, []), thresholds) for target in targets]
    _demote_shared_sources(mappings)
    return mappings


def rank(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=lambda c: (c.vetoed_by is not None, -c.score, c.source.key))


def _decide(target: FieldProfile, candidates: list[Candidate], thresholds: Thresholds) -> FieldMapping:
    ranked = rank(candidates)
    alternatives = tuple(ranked[: thresholds.alternatives_kept])
    derived_value = _discriminator_value(target.node)
    if derived_value is not None:
        return FieldMapping(
            target=target.node,
            status=MappingStatus.DERIVED,
            alternatives=alternatives,
            notes=[f"constant {derived_value!r}: set by the variant this record is routed to"],
        )

    viable = [c for c in ranked if c.vetoed_by is None]
    best = viable[0] if viable and viable[0].score >= thresholds.review else semantic_fallback(viable, thresholds.review)
    if best is None:
        return FieldMapping(target=target.node, status=MappingStatus.UNMAPPED, alternatives=alternatives)

    notes = _requirement_notes(target.node, best)
    rival = next((c for c in viable if c is not best and not _equivalent(c.source, best.source)), None)
    status = MappingStatus.AUTO if best.score >= thresholds.auto else MappingStatus.REVIEW
    reasons = review_reasons(target.node, best, thresholds.auto)
    if reasons:
        status = MappingStatus.REVIEW
        notes.extend(reasons)
    if status is MappingStatus.AUTO and rival and best.score - rival.score < thresholds.ambiguity_margin:
        status = MappingStatus.REVIEW
        notes.append(f"close alternative {rival.source.api}:{rival.source.path} ({rival.score:.2f})")
    return FieldMapping(
        target=target.node,
        status=status,
        chosen=best,
        alternatives=tuple(c for c in alternatives if c is not best),
        notes=notes,
    )


def _discriminator_value(node: FieldNode) -> str | None:
    if not node.condition or len(node.enum) != 1:
        return None
    for clause in node.condition.split(" and "):
        prop, _, value = clause.partition(" = ")
        if node.name == prop and value == node.enum[0]:
            return value
    return None


def _equivalent(a: FieldNode, b: FieldNode) -> bool:
    """The same field reached through a list and a detail endpoint of one API is one choice, not two."""
    return a.api == b.api and a.name == b.name and a.type == b.type


def _requirement_notes(target: FieldNode, candidate: Candidate) -> list[str]:
    notes = []
    if target.required and (not candidate.source.required or candidate.source.nullable):
        notes.append("upstream requires this field; source may omit it")
    unmapped = next((step.params.get("unmapped") for step in candidate.transforms if step.params.get("unmapped")), None)
    if unmapped:
        notes.append(f"enum values with no upstream match: {', '.join(unmapped)}")
    return notes


def _demote_shared_sources(mappings: list[FieldMapping]) -> None:
    claims: dict[tuple[str, str | None, str], list[FieldMapping]] = {}
    for mapping in mappings:
        if mapping.chosen and mapping.status in (MappingStatus.AUTO, MappingStatus.REVIEW):
            key = (mapping.target.endpoint, mapping.target.variant, mapping.chosen.source.key)
            claims.setdefault(key, []).append(mapping)
    for claimants in claims.values():
        if len(claimants) < 2:
            continue
        claimants.sort(key=lambda m: (-m.chosen.score, m.target.path))
        winner = claimants[0]
        for loser in claimants[1:]:
            loser.status = MappingStatus.REVIEW
            loser.notes.append(f"same source also fills {winner.target.path} ({winner.chosen.score:.2f})")
