"""Explain a draft without changing the saved decision or carrying over its old rationale."""

from dataclasses import replace

from api_mapper.models import Candidate, FieldMapping, MappingStatus
from api_mapper.reporting.comparison import explain_comparison
from api_mapper.transforms.editor import parse_steps
from api_mapper.transforms.enum_normalization import validate_enum_outputs


def explain_draft(mapping: FieldMapping, candidate: Candidate, raw_steps: object) -> dict:
    steps = parse_steps(raw_steps)
    if steps is not None:
        validate_enum_outputs(steps, mapping.target)
        candidate = replace(candidate, transforms=steps)
    alternatives = tuple(
        c for c in (mapping.chosen, *mapping.alternatives) if c and c.source.key != candidate.source.key
    )
    draft = FieldMapping(mapping.target, MappingStatus.MANUAL, candidate, alternatives)
    explanation = explain_comparison(draft)
    explanation["summary"] = (
        f"Previewing {candidate.source.api}:{candidate.source.path} → {mapping.target.path}. "
        "This is your draft choice; review the supporting evidence and uncertainties before saving."
    )
    explanation["method"] = (
        "Explanation from recorded matching evidence. Compatibility scores describe the source pair; "
        "conversion requirements reflect your current draft. Use Try a value to check its output."
    )
    return explanation
