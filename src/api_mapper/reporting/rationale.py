"""Readable explanations grounded in recorded signals and the supplied API definitions."""

from api_mapper.models import Candidate, EvidenceEffect, FieldNode, Signal

SIGNAL_NAMES = {
    Signal.NAME: "field-name meaning",
    Signal.SPELLING: "name spelling",
    Signal.TYPE: "data type",
    Signal.ENUM: "allowed values",
    Signal.SAMPLE: "example values",
    Signal.DESCRIPTION: "description",
    Signal.STRUCTURE: "record structure",
    Signal.CONTEXT: "API context",
    Signal.ENDPOINT: "endpoint context",
    Signal.LOCAL_NLP: "local NLP similarity",
}


def support(candidate: Candidate) -> list[str]:
    purpose = [e.detail for e in candidate.evidence if e.signal is Signal.PURPOSE_SUPPORT]
    signals = sorted(
        (e for e in candidate.evidence if e.effect is EvidenceEffect.WEIGHTED and e.weight > 0 and e.score >= 0.5),
        key=lambda e: (-e.score * e.weight, e.signal),
    )
    reasons = [
        f"The local model finds the supplied field descriptions and context similar (similarity {e.score:.2f})."
        if e.signal is Signal.LOCAL_NLP
        else f"{SIGNAL_NAMES.get(e.signal, e.signal)}: {e.detail}"
        for e in signals[:3]
    ]
    return list(dict.fromkeys([*purpose, *reasons]))


def concerns(candidate: Candidate) -> list[str]:
    found = [
        "Field names alone do not identify the requested concept; check the API definitions."
        if e.signal is Signal.ANCHOR
        else e.detail
        for e in candidate.evidence
        if e.effect is not EvidenceEffect.WEIGHTED
        or e.signal in {Signal.BODY_CONTEXT, Signal.IDENTITY_REVIEW, Signal.NLP_ONLY, Signal.DOCUMENTATION_SAMPLES}
    ]
    if candidate.vetoed_by:
        found.insert(0, candidate.vetoed_by)
    if any(e.signal is Signal.LOCAL_NLP for e in candidate.evidence):
        found.append(
            "Local NLP measures similarity; it does not prove that the fields refer to the same fact or record."
        )
    if not any(e.signal is Signal.PURPOSE_SUPPORT for e in candidate.evidence):
        found.append(
            "The recorded evidence does not establish matching business definitions. Check the API references below."
        )
    return list(dict.fromkeys(found))


def requirements(target: FieldNode, candidate: Candidate) -> list[str]:
    source = candidate.source
    found = [f"Conversion: {step.description}" for step in candidate.transforms]
    if target.required and (source.nullable or not source.required):
        found.append("The output is required, but this source may be missing or null.")
    if source.type != target.type and not candidate.transforms:
        found.append(f"Confirm how {source.type} becomes {target.type}; no conversion step is configured.")
    for label, node in (("Output", target), ("Source", source)):
        if node.condition:
            found.append(f"{label} applies when {node.condition}.")
    if source.array_depth > target.array_depth:
        found.append("Choose the correct item from the source list; confirm the record selection or join.")
    for step in candidate.transforms:
        if step.params.get("unmapped"):
            found.append("Values without an enum mapping: " + ", ".join(map(str, step.params["unmapped"])))
    return list(dict.fromkeys(found))


def references(target: FieldNode, source: FieldNode | None) -> list[dict]:
    found = []
    for side, node in (("Output", target), ("Source", source)):
        if node is None:
            continue
        if node.description:
            found.append(
                {
                    "side": side,
                    "location": f"{node.api} · {node.endpoint} · {node.path}.description",
                    "text": node.description,
                    "kind": "API definition",
                }
            )
        for clue in (*node.documentation, *node.context_clues):
            found.append({"side": side, "location": clue.location, "text": clue.text, "kind": "API context"})
        if node.sample_sources:
            found.append(
                {
                    "side": side,
                    "location": ", ".join(node.sample_sources),
                    "text": node.sample_context
                    or "Response examples inform shape and value compatibility, not field meaning.",
                    "kind": "Response examples",
                }
            )
    return found


def ranking_difference(chosen: Candidate, rival: Candidate) -> str:
    left = {
        e.signal: e.score * e.weight for e in chosen.evidence if e.effect is EvidenceEffect.WEIGHTED and e.weight > 0
    }
    right = {
        e.signal: e.score * e.weight for e in rival.evidence if e.effect is EvidenceEffect.WEIGHTED and e.weight > 0
    }
    stronger = sorted(
        (key for key in left.keys() & right.keys() if left[key] > right[key] + 0.01),
        key=lambda key: (-(left[key] - right[key]), key),
    )
    detail = (
        (
            " The selected source has stronger evidence for "
            + ", ".join(SIGNAL_NAMES.get(key, key) for key in stronger[:2])
            + "."
        )
        if stronger
        else ""
    )
    return (
        f"Ranking score {rival.score:.3f} versus {chosen.score:.3f} for the selected source."
        + detail
        + " Scores are ranking signals, not probabilities of correctness."
    )
