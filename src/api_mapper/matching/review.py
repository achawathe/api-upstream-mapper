"""Review safeguards shared by ordinary rules and local semantic suggestions."""

from api_mapper.models import Candidate, FieldNode


def definition_preferred(candidate: Candidate) -> bool:
    return any(e.signal == "definition_preferred" for e in candidate.evidence)


def semantic_fallback(candidates: list[Candidate], review_threshold: float) -> Candidate | None:
    supported = [(e.score, c) for c in candidates for e in c.evidence
                 if e.signal in {"semantic_review", "context_review"} and e.score >= review_threshold]
    return min(supported, key=lambda pair: (-pair[0], -pair[1].score, pair[1].source.key))[1] if supported else None


def review_reasons(target: FieldNode, candidate: Candidate, auto_threshold: float) -> list[str]:
    reasons = []
    evidence = candidate.evidence
    if any(step.params.get('target_origin') == 'documentation' or step.params.get('citations') or step.params.get('open_source') for step in candidate.transforms):
        reasons.append('confirm suggested value translations against API definitions and handling of unknown downstream strings')
    if any(e.signal == 'documentation_context' for e in evidence):
        reasons.append('attached documentation supports interpretation; confirm field meaning and any conversion')
    if any(e.signal == "purpose_uncertain" for e in evidence):
        reasons.append("field-purpose evidence is uncertain or conflicting; confirm before accepting")
    if any(e.signal == "context_review" for e in evidence):
        reasons.append("context supports this candidate despite its naming; confirm purpose and record identity")
    if any(e.signal == "body_context" for e in evidence):
        reasons.append("confirm JSON body bindings, source identifier compatibility and record selection")
    if any(e.signal == "identity_review" for e in evidence):
        reasons.append("source reference may label this record rather than identify the related record")
    if any(_mostly_unmapped(step.params) for step in candidate.transforms):
        reasons.append("most source enum values lack upstream equivalents; confirm the value mapping")
    type_score = next((e.score for e in evidence if e.signal == "type"), 0.0)
    if target.format in {"date", "date-time"} and type_score < 0.75:
        reasons.append("date conversion lacks format evidence; confirm the source represents the required event")
    rules_score = next((e.score for e in evidence if e.signal == "rules_score"), candidate.score)
    if any(e.signal == "nlp_only" for e in evidence) or rules_score < auto_threshold <= candidate.score:
        reasons.append("local NLP supports this suggestion; confirm the field meaning before accepting")
    if any(e.signal == "semantic_review" for e in evidence) and candidate.score < auto_threshold:
        reasons.append("descriptive similarity supports review; rule confidence remains below the automatic threshold")
    if candidate.source.array_depth > target.array_depth:
        reasons.append("source has additional array levels; confirm which item supplies this value")
    if target.type in {"number", "integer"} and candidate.source.type == "string" and type_score < 0.85:
        reasons.append("string-to-number conversion lacks numeric sample evidence; confirm before accepting")
    return reasons


def _mostly_unmapped(params: dict) -> bool:
    unmapped = params.get("unmapped") or []
    mapped = params.get("mapping") or {}
    return bool(unmapped) and len(unmapped) > len(mapped)
