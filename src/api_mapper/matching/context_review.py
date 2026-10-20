"""Eligibility for advisory definition/NLP matches, independent of lexical ranking."""

from api_mapper.models import Evidence, EvidenceEffect, FieldProfile
from api_mapper.transforms.inference import TypeFit


def can_review(
    target: FieldProfile,
    source: FieldProfile,
    fit: TypeFit,
    evidence: list[Evidence],
    *,
    definition_match: bool = False,
) -> bool:
    if fit.veto or fit.score < 0.85:
        return False
    record_selection = (
        target.node.array_depth == 0
        and source.node.array_depth == 1
        and not source.node.path.endswith("[]")
        and bool(target.endpoint_concepts)
        and source.collection[-1:] == target.endpoint_concepts[-1:]
    )
    if target.node.array_depth != source.node.array_depth and not record_selection:
        return False
    allowed = {"anchor", "spelling"}
    if definition_match:
        allowed.add("enum")
    if record_selection:
        allowed.add("list-to-one")
    return not any(
        e.effect is EvidenceEffect.VETO or (e.effect is EvidenceEffect.MULTIPLIER and e.signal not in allowed)
        for e in evidence
    )
