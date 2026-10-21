"""Review suggestions for values whose own name says nothing, from the context both responses share.

`snapshot.weather.city.{key}` holds one number per city: its name only says what its keys
are. When the upstream request picks the entry (`{city}`), both sides share a context word
(`weather`), the source is the only unclaimed field of a fitting type in its response, and the
target is the only unmapped field of that type in its own, the source is suggested for review.
Never automatic: nothing but context and type connects the two.
"""

from collections import Counter
from dataclasses import replace

from api_mapper.matching.context_review import can_review
from api_mapper.matching.engine import PreparedMatch
from api_mapper.matching.review import map_entry_reason
from api_mapper.models import Evidence, FieldMapping, FieldProfile, MappingStatus, Signal
from api_mapper.models.field_node import MAP_VALUE_SEGMENT
from api_mapper.normalize.lexicon import Lexicon

MIN_TYPE_FIT = 0.9  # native types only: numeric text such as a version "2.1" is not a rival quantity
_CLAIMED = (MappingStatus.AUTO, MappingStatus.REVIEW, MappingStatus.MANUAL)


def suggest_from_context(mappings: list[FieldMapping], prepared: PreparedMatch, lexicon: Lexicon) -> None:
    claimed = {m.chosen.source.key for m in mappings if m.chosen and m.status in _CLAIMED}
    open_by_type = Counter(_slot(m.target) for m in mappings if m.status is MappingStatus.UNMAPPED)
    responses: dict[tuple[str, str], list[FieldProfile]] = {}
    for source in prepared.sources.values():
        responses.setdefault((source.node.api, source.node.endpoint), []).append(source)
    for mapping in mappings:
        if mapping.status is not MappingStatus.UNMAPPED or open_by_type[_slot(mapping.target)] != 1:
            continue
        target = prepared.targets[mapping.target.key]
        options = []
        for source in prepared.sources.values():
            context = _shared_context(target, source, lexicon) if _named_only_by_keys(source, target) else []
            if not context or source.node.key in claimed or not _fits(prepared, target, source):
                continue
            response = responses[(source.node.api, source.node.endpoint)]
            rivals = [
                s for s in response if s is not source and s.node.key not in claimed and _fits(prepared, target, s)
            ]
            if not rivals:
                options.append((source, context))
        if len(options) != 1:
            continue
        source, context = options[0]
        candidate = prepared.scorer.score(target, source, gate=False)
        fit = prepared.scorer.fitter.fit(target.node, source.node, source.temporal)
        if candidate.vetoed_by or not can_review(target, source, fit, list(candidate.evidence)):
            continue
        detail = (
            f"its name only says what its keys are; it is the only {mapping.target.type} value in the shared "
            f"{', '.join(context)} context, and this request selects its entry"
        )
        mapping.status = MappingStatus.REVIEW
        mapping.chosen = replace(
            candidate, evidence=(*candidate.evidence, Evidence(Signal.CONTEXT_REVIEW, 1.0, 0.0, detail))
        )
        mapping.notes.extend(
            [f"suggested from context alone: {detail}; confirm before accepting", map_entry_reason(source.node)]
        )


def _slot(target) -> tuple:
    return target.endpoint, target.variant, target.type


def _named_only_by_keys(source: FieldProfile, target: FieldProfile) -> bool:
    """A scalar map value whose map is named after its keys, and the request supplies such a key."""
    return source.node.path.endswith(f".{MAP_VALUE_SEGMENT}") and frozenset(source.leaf) in target.endpoint_inputs


def _shared_context(target: FieldProfile, source: FieldProfile, lexicon: Lexicon) -> list[str]:
    ignored = {*source.leaf, *lexicon.generic, *lexicon.weak}
    target_words = {*target.endpoint_concepts, *target.parent}
    source_words = {*source.endpoint_concepts, *source.bag}
    return sorted((target_words & source_words) - ignored)


def _fits(prepared: PreparedMatch, target: FieldProfile, source: FieldProfile) -> bool:
    fit = prepared.scorer.fitter.fit(target.node, source.node, source.temporal)
    return not fit.veto and fit.score >= MIN_TYPE_FIT
