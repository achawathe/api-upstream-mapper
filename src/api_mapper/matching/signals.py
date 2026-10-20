"""Independent pieces of evidence that a source field fills a target field.

Each signal returns a score in [0, 1] and a human-readable detail, or None when it
has nothing to say about the pair (for example, enum overlap when neither side is an enum).
"""

import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from api_mapper.matching.reachability import Reachability
from api_mapper.matching.similarity import (
    ConceptWeights,
    align_qualifier_words,
    bag_similarity,
)
from api_mapper.models import FieldProfile, TransformKind
from api_mapper.normalize.enum_contract import enum_contract
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.transforms.enum_mapping import EnumMapper
from api_mapper.transforms.inference import TypeFit

SignalResult = tuple[float, str] | None

_VALUE_SHAPES = (
    ("timestamp", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")),
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("uuid", re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)),
    ("email", re.compile(r"^[^@\s]+@[^@\s]+$")),
    ("code3", re.compile(r"^[A-Z]{3}$")),
    ("code2", re.compile(r"^[A-Z]{2}$")),
    ("digits", re.compile(r"^\d+$")),
    ("decimal-text", re.compile(r"^-?\d+\.\d+$")),
)


DESCRIPTION_NAME_CREDIT = 0.75
SAME_KIND = 0.5
_STRONG_SHAPES = frozenset(
    {"timestamp", "date", "uuid", "email", "code3", "code2", "digits", "decimal-text", "boolean"}
)
_NUMERIC_SHAPES = frozenset({"digits", "decimal-text"})


@dataclass(frozen=True)
class SignalContext:
    lexicon: Lexicon
    weights: ConceptWeights
    enum_mapper: EnumMapper
    reachability: Reachability | None = None


def name_signal(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> tuple[float, str]:
    target_bag = align_qualifier_words(target.bag, source.bag, source.families, ctx.lexicon)
    source_bag = align_qualifier_words(source.bag, target.bag, target.families, ctx.lexicon)
    score, alignment = bag_similarity(target_bag, source_bag, ctx.weights, ctx.lexicon)
    matched = ", ".join(x if x == y else f"{x}~{y}" for x, y, _ in alignment) or "nothing"
    defined = _defined_by_description(target, source, ctx)
    if defined > score:
        return defined, f"target description names the source ({matched} by name)"
    return score, f"concepts matched: {matched}"


def _defined_by_description(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> float:
    """Spec authors often define a field in prose: bankId is "the 9-digit routing transit number".

    Counts only when every main concept of the source name appears in the target's
    description, scaled by how much of what the target is about the source name covers.
    """
    concepts = [c for c, share in source.bag.items() if share >= 0.5]
    if not concepts or not all(c in target.description_concepts for c in concepts):
        return 0.0
    if len(concepts) < 2 and all(c in ctx.lexicon.generic for c in concepts):
        return 0.0
    if not target.anchor:
        return 0.0
    covered = sum(1 for a in target.anchor if any(ctx.lexicon.relatedness(a, c) > 0 for c in concepts))
    return DESCRIPTION_NAME_CREDIT * covered / len(target.anchor)


def string_signal(target: FieldProfile, source: FieldProfile) -> tuple[float, str]:
    if target.leaf_is_generic or source.leaf_is_generic:
        score = fuzz.ratio(target.compact_context, source.compact_context) / 100
    else:
        score = fuzz.ratio(target.compact_leaf, source.compact_leaf) / 100
    return score, f"spelling similarity {score:.0%}"


def context_signal(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> SignalResult:
    """Compares the objects both fields sit in: `telephones[].network` is not `networks[].rail`."""
    if target.leaf_is_generic or source.leaf_is_generic or not target.parent or not source.parent:
        return None
    score, alignment = bag_similarity(
        {c: 1.0 for c in target.parent}, {c: 1.0 for c in source.parent}, ctx.weights, ctx.lexicon
    )
    shared = ", ".join(x for x, _, _ in alignment) or "nothing"
    return score, f"parent objects share {shared}"


def anchored(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> bool:
    """True when what the target is about appears in the source name, not just shared context words."""
    if not target.anchor:
        return True
    source_concepts = [c for c, share in source.bag.items() if share >= 0.5]
    return any(ctx.lexicon.relatedness(a, c) > 0 for a in target.anchor for c in source_concepts)


def collection_agrees(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> bool:
    """Fields inside an array must describe the same kind of item.

    Two arrays must share their head noun (`transactions[]` ~ `entries[]`, but not
    `assetTransferNetworks[]` ~ `transfers[]`). A source outside any array is read once
    per item, so its endpoint only needs to be about the same thing (`holders[]` ~ `/parties/{id}`).
    """
    target_collection = target.collection
    if (
        not target_collection
        and source.collection
        and target.node.array_depth == 0
        and target.endpoint_concepts
        and target.endpoint_concepts[-1] in ctx.lexicon.known_words
    ):
        target_collection = target.endpoint_concepts[-1:]
    if not target_collection:
        return True
    if source.collection:
        target_head, source_head = target_collection[-1], source.collection[-1]
        return ctx.lexicon.relatedness(target_head, source_head) >= SAME_KIND
    return any(ctx.lexicon.relatedness(t, s) >= SAME_KIND for t in target.collection for s in source.endpoint_concepts)


def type_signal(fit: TypeFit) -> tuple[float, str]:
    return fit.score, fit.detail or "types compatible"


def enum_signal(fit: TypeFit, target: FieldProfile) -> SignalResult:
    if fit.enum_mapping is None:
        return None
    mapping = fit.enum_mapping
    score = max(mapping.source_coverage, mapping.target_coverage(len(enum_contract(target.node).values)))
    unmapped = f"; unmatched {', '.join(mapping.unmapped)}" if mapping.unmapped else ""
    return score, f"{len(mapping.mapping)}/{len(mapping.mapping) + len(mapping.unmapped)} values match{unmapped}"


def value_signal(target: FieldProfile, source: FieldProfile, fit: TypeFit) -> SignalResult:
    if target.node.enum or any(step.kind is not TransformKind.ENUM_MAP for step in fit.steps):
        return None
    example, target_example = source.node.example, target.node.example
    if example is None or target_example is None:
        return None
    target_shape, source_shape = _shape(target_example), _shape(example)
    if target_shape == source_shape:
        return 1.0, f"samples share the {target_shape} shape"
    return 0.2, f"sample shapes differ ({target_shape} vs {source_shape})"


def shapes_conflict(target: FieldProfile, source: FieldProfile, fit: TypeFit) -> str | None:
    """Digits versus letters, dates versus codes: sample values that cannot be the same kind of data."""
    if target.node.enum or source.node.enum or fit.steps:
        return None
    if target.node.example is None or source.node.example is None:
        return None
    target_shape, source_shape = _shape(target.node.example), _shape(source.node.example)
    if target_shape in _STRONG_SHAPES and source_shape in _STRONG_SHAPES and target_shape != source_shape:
        if {target_shape, source_shape} <= _NUMERIC_SHAPES:
            return None
        return f"sample {target.node.example!r} vs {source.node.example!r}"
    return None


def description_signal(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> SignalResult:
    best = max(
        _coverage(source.bag, target.description_concepts, ctx.weights),
        _coverage(target.bag, source.description_concepts, ctx.weights),
    )
    if best <= 0:
        return None
    return best, f"name appears in the other field's description ({best:.0%})"


def structure_signal(target: FieldProfile, source: FieldProfile) -> tuple[float, str]:
    difference = abs(target.node.array_depth - source.node.array_depth)
    score = {0: 1.0, 1: 0.6}.get(difference, 0.3)
    return score, f"array depth {target.node.array_depth} vs {source.node.array_depth}"


def endpoint_signal(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> SignalResult:
    target_bag = {c: 1.0 for c in target.endpoint_concepts}
    source_bag = {c: 1.0 for c in source.endpoint_concepts}
    score, alignment = bag_similarity(target_bag, source_bag, ctx.weights, ctx.lexicon)
    if score <= 0:
        return None
    return score, f"endpoints share {', '.join(x for x, _, _ in alignment)}"


def qualifier_relation(target: FieldProfile, source: FieldProfile) -> str:
    """'agree', 'conflict' or 'neutral' for account families (deposit, credit, loan...)."""
    target_families, source_families = target.families, source.families
    if not target_families or not source_families:
        return "neutral"
    return "agree" if target_families & source_families else "conflict"


def modifier_difference(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> tuple[str, str] | None:
    """Modifiers that pick a different value of the same quantity: `last` vs `minimum`, or a
    defining modifier such as `foreign` on one side only. Returns both sides when they differ."""
    target_modifiers = _modifiers(target, ctx)
    source_modifiers = _modifiers(source, ctx)
    if target_modifiers and source_modifiers:
        if any(ctx.lexicon.relatedness(t, s) > 0 for t in target_modifiers for s in source_modifiers):
            return None
        return "/".join(sorted(target_modifiers)), "/".join(sorted(source_modifiers))
    one_side = (target_modifiers or source_modifiers) & ctx.lexicon.defining_modifiers
    if not one_side:
        return None
    return "/".join(sorted(target_modifiers)) or "none", "/".join(sorted(source_modifiers)) or "none"


def per_item_fanout(target: FieldProfile, source: FieldProfile) -> bool:
    """A list of X filled by calling X's own detail endpoint once per item, rather than from a list of X."""
    if target.node.array_depth <= source.node.array_depth or not target.collection:
        return False
    return target.collection[-1] in source.endpoint_concepts[-1:]


def _modifiers(profile: FieldProfile, ctx: SignalContext) -> set[str]:
    return {c for c, share in profile.bag.items() if share >= 0.5 and c in ctx.lexicon.exclusive_modifiers}


def unreachable(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> bool:
    if ctx.reachability is None:
        return False
    return not ctx.reachability.reachable(target.endpoint_inputs, (source.node.api, source.node.endpoint))


def different_record(target: FieldProfile, source: FieldProfile, ctx: SignalContext) -> tuple[str, str] | None:
    """A single value of one record must not come from an endpoint about another record:
    an account's nickname is not a payee's nickname, even when the payee is reachable."""
    if target.node.array_depth or source.node.array_depth or not target.record or not source.record:
        return None
    if any(ctx.lexicon.relatedness(t, s) > 0 for t in target.record for s in source.record):
        return None
    return "/".join(sorted(target.record)), "/".join(sorted(source.record))


def role_mismatch(target: FieldProfile, source: FieldProfile) -> frozenset[str]:
    return target.roles ^ source.roles


def _coverage(bag: dict[str, float], description: frozenset[str], weights: ConceptWeights) -> float:
    if not description or not bag:
        return 0.0
    total = sum(share * weights(c) for c, share in bag.items())
    covered = sum(share * weights(c) for c, share in bag.items() if c in description)
    return covered / total if total else 0.0


def _shape(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    text = str(value)
    for name, pattern in _VALUE_SHAPES:
        if pattern.match(text):
            return name
    return "text"
