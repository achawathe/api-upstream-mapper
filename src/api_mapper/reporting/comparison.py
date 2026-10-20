"""Explain decisions using recorded evidence, never generated or unverified rationales."""

from api_mapper.models import Candidate, FieldMapping, MappingStatus, Signal
from api_mapper.reporting.rationale import (
    concerns,
    ranking_difference,
    references,
    requirements,
    support,
)


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
    elif mapping.status is MappingStatus.REVIEW and any(e.signal is Signal.CONTEXT_REVIEW for e in chosen.evidence):
        summary = (
            "Field-purpose evidence supports this suggestion. "
            "Confirm the interpretation and record identity before accepting."
        )
    else:
        summary = "Selected by the combined matching evidence; scores are ranking signals, not probabilities."
    if chosen:
        summary = f"{chosen.source.api}:{chosen.source.path} → {mapping.target.path}. " + summary
    alternatives = []
    for candidate in mapping.alternatives:
        issues = concerns(candidate)
        if candidate.vetoed_by:
            reason = "Excluded: " + candidate.vetoed_by
        elif chosen and _definition_preferred(chosen) and not _definition_preferred(candidate):
            reason = (
                "The selected source has matching explicit purpose definitions; this alternative lacks that support."
            )
        elif chosen:
            reason = ranking_difference(chosen, candidate)
            if issues:
                reason += " " + issues[0]
        else:
            reason = "Insufficient support for selection; field meaning remains unconfirmed."
        alternatives.append(
            {
                "source_key": candidate.source.key,
                "source": f"{candidate.source.api}:{candidate.source.path}",
                "score": candidate.score,
                "reason": reason,
                "support": support(candidate),
                "concerns": issues,
                "references": references(mapping.target, candidate.source),
            }
        )
    issues = concerns(chosen) if chosen else []
    if mapping.status in (MappingStatus.AUTO, MappingStatus.REVIEW):
        issues = list(dict.fromkeys([*issues, *mapping.notes]))
    return {
        "summary": summary,
        "support": support(chosen) if chosen else [],
        "concerns": issues,
        "alternatives": alternatives,
        "requirements": requirements(mapping.target, chosen) if chosen else [],
        "references": references(mapping.target, chosen.source if chosen else None),
        "method": "Explanation from recorded matching evidence and supplied API definitions.",
    }


def _definition_preferred(candidate: Candidate) -> bool:
    return any(e.signal is Signal.DEFINITION_PREFERRED for e in candidate.evidence)
