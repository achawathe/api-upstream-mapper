"""Local similarity supplements rules; it never weakens existing rule evidence.

A strong descriptive match can be surfaced for review despite a missing lexical
anchor. Structural, role, enum, reachability and type safeguards still apply.
"""

from api_mapper.matching.context_review import can_review
from api_mapper.models import Evidence, FieldProfile, Signal
from api_mapper.transforms.inference import TypeFit


def add_semantic_evidence(
    evidence: list[Evidence],
    target: FieldProfile,
    source: FieldProfile,
    fit: TypeFit,
    similarity: float,
    weight: float,
    rules_score: float,
    semantic_match: bool,
    lexical_match: bool,
) -> None:
    evidence.append(Evidence(Signal.RULES_SCORE, round(rules_score, 4), 0.0, "confidence before local NLP"))
    evidence.append(
        Evidence(
            Signal.LOCAL_NLP,
            similarity,
            weight,
            "local cosine similarity of field context and cited definitions; "
            "zero weight when it would dilute rule evidence",
        )
    )
    if semantic_match and not lexical_match:
        evidence.append(Evidence(Signal.NLP_ONLY, 1.0, 0.0, "candidate discovered by local NLP; requires human review"))
    target_defined = bool(target.node.description.strip() or target.node.documentation)
    source_defined = bool(source.node.description.strip() or source.node.documentation)
    if semantic_match and target_defined and source_defined and can_review(target, source, fit, evidence):
        evidence.append(
            Evidence(
                Signal.SEMANTIC_REVIEW,
                similarity,
                0.0,
                "strong descriptive similarity supports review despite weak lexical evidence",
            )
        )
