"""Explain decisions using recorded evidence, never generated or unverified rationales."""

from api_mapper.models import Candidate, EvidenceEffect, FieldMapping, MappingStatus


def explain_comparison(mapping: FieldMapping) -> dict:
    chosen = mapping.chosen
    if mapping.status is MappingStatus.DERIVED:
        summary = "The schema's variant definition supplies this value; no downstream source is required."
    elif mapping.status is MappingStatus.REJECTED:
        summary = "Rejected by a reviewer. The evidence below records the automated alternatives."
    elif not chosen:
        summary = "No source selected. The alternatives below show the available evidence and conflicts."
    elif mapping.status is MappingStatus.MANUAL:
        summary = "Selected by a reviewer. The automated evidence below may still contain conflicts."
    elif mapping.status is MappingStatus.REVIEW and any(e.signal == "context_review" for e in chosen.evidence):
        summary = "Field-purpose evidence supports this suggestion. Confirm the interpretation and record identity before accepting."
    else:
        summary = "Selected by the combined matching evidence; scores are ranking signals, not probabilities."
    alternatives = []
    for candidate in mapping.alternatives:
        concerns = _concerns(candidate)
        if candidate.vetoed_by:
            reason = "Excluded: " + candidate.vetoed_by
        elif concerns:
            reason = "; ".join(concerns[:2])
        elif chosen and _definition_preferred(chosen) and not _definition_preferred(candidate):
            reason = "The selected source has matching explicit purpose definitions; this alternative lacks that support."
        elif chosen:
            reason = (f"Ranking score {candidate.score:.3f} versus {chosen.score:.3f} for the selected source. "
                      "The available evidence does not establish a purpose conflict.")
        else:
            reason = "Insufficient support for selection; field meaning remains unconfirmed."
        alternatives.append({"source_key": candidate.source.key, "source": f"{candidate.source.api}:{candidate.source.path}",
                             "score": candidate.score, "reason": reason, "support": _support(candidate), "concerns": concerns})
    return {"summary": summary, "support": _support(chosen) if chosen else [],
            "concerns": _concerns(chosen) if chosen else [], "alternatives": alternatives}


def _support(candidate: Candidate) -> list[str]:
    purpose = [e.detail for e in candidate.evidence if e.signal in {"purpose_support", "documentation_context"}]
    signals = sorted((e for e in candidate.evidence if e.effect is EvidenceEffect.WEIGHTED and e.weight > 0 and e.score >= 0.5),
                     key=lambda e: (-e.score * e.weight, e.signal))
    return [*dict.fromkeys(purpose), *(f"{e.signal}: {e.detail}" for e in signals[:3])]


def _definition_preferred(candidate: Candidate) -> bool:
    return any(e.signal == "definition_preferred" for e in candidate.evidence)


def _concerns(candidate: Candidate) -> list[str]:
    return list(dict.fromkeys(e.detail for e in candidate.evidence if e.effect is not EvidenceEffect.WEIGHTED))
