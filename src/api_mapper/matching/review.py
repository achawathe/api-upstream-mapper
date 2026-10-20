"""Review safeguards shared by ordinary rules and local semantic suggestions."""

from api_mapper.models import Candidate, FieldNode, Signal


def definition_preferred(candidate: Candidate) -> bool:
    return any(e.signal is Signal.DEFINITION_PREFERRED for e in candidate.evidence)


def semantic_fallback(candidates: list[Candidate], review_threshold: float) -> Candidate | None:
    supported = [
        (e.score, c)
        for c in candidates
        for e in c.evidence
        if e.signal in {Signal.SEMANTIC_REVIEW, Signal.CONTEXT_REVIEW} and e.score >= review_threshold
    ]
    return min(supported, key=lambda pair: (-pair[0], -pair[1].score, pair[1].source.key))[1] if supported else None


def review_reasons(target: FieldNode, candidate: Candidate, auto_threshold: float) -> list[str]:
    reasons = []
    evidence = candidate.evidence
    if any(
        step.params.get("target_origin") == "documentation" or step.params.get("citations")
        for step in candidate.transforms
    ):
        reasons.append(
            "confirm suggested value translations against API definitions and handling of unknown downstream strings"
        )
    if any(e.signal is Signal.DOCUMENTATION_CONTEXT for e in evidence):
        reasons.append("attached documentation supports interpretation; confirm field meaning and any conversion")
    if any(e.signal is Signal.PURPOSE_UNCERTAIN for e in evidence):
        reasons.append("field-purpose evidence is uncertain or conflicting; confirm before accepting")
    if any(e.signal is Signal.CONTEXT_REVIEW for e in evidence):
        reasons.append("context supports this candidate despite its naming; confirm purpose and record identity")
    if any(e.signal is Signal.BODY_CONTEXT for e in evidence):
        reasons.append("confirm JSON body bindings, source identifier compatibility and record selection")
    if any(e.signal is Signal.IDENTITY_REVIEW for e in evidence):
        reasons.append("source reference may label this record rather than identify the related record")
    type_score = next((e.score for e in evidence if e.signal is Signal.TYPE), 0.0)
    if target.format in {"date", "date-time"} and type_score < 0.75:
        reasons.append("date conversion lacks format evidence; confirm the source represents the required event")
    rules_score = next((e.score for e in evidence if e.signal is Signal.RULES_SCORE), candidate.score)
    if any(e.signal is Signal.NLP_ONLY for e in evidence) or rules_score < auto_threshold <= candidate.score:
        reasons.append("local NLP supports this suggestion; confirm the field meaning before accepting")
    if any(e.signal is Signal.SEMANTIC_REVIEW for e in evidence) and candidate.score < auto_threshold:
        reasons.append("descriptive similarity supports review; rule confidence remains below the automatic threshold")
    if entry := map_entry_reason(candidate.source):
        reasons.append(entry)
    if candidate.source.array_depth > target.array_depth:
        reasons.append("source has additional array levels; confirm which item supplies this value")
    if target.type in {"number", "integer"} and candidate.source.type == "string" and type_score < 0.85:
        reasons.append("string-to-number conversion lacks numeric sample evidence; confirm before accepting")
    return reasons


def map_entry_reason(source: FieldNode) -> str | None:
    if source.map_path is None:
        return None
    what = "the key of each entry" if source.is_map_key else "one value per entry"
    return (
        f"source is {what} of {source.map_path}, whose keys are data; "
        "confirm which entry this request selects, for example by a path parameter"
    )


def unrouted_enum_values(params: dict, routed_elsewhere: set[str]) -> list[str] | None:
    """Source values no variant accepts, when they outnumber the ones this variant maps.

    A variant's map leaves out values that belong to its siblings (`CC` is a credit account,
    not a deposit account); only values that no variant accepts need a person to decide.
    """
    mapped = params.get("mapping") or {}
    orphans = [value for value in params.get("unmapped") or [] if value not in routed_elsewhere]
    return orphans if orphans and len(orphans) > len(mapped) else None
