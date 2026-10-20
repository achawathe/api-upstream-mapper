"""Combines signals into one confidence score per (target, source) pair.

score = weighted mean of the applicable signals, times any penalty multipliers.
A veto (incompatible types) zeroes the score but keeps the candidate, so the
report can say why an obvious-looking name match was refused.
"""

from dataclasses import dataclass

from api_mapper.matching import signals
from api_mapper.matching.context_review import can_review
from api_mapper.matching.meaning import MeaningMatcher
from api_mapper.matching.purpose import compare_purposes, comparison_evidence
from api_mapper.matching.semantic import SemanticIndex
from api_mapper.matching.semantic_evidence import add_semantic_evidence
from api_mapper.matching.signals import SignalContext
from api_mapper.models import Candidate, Evidence, EvidenceEffect, FieldProfile, Signal
from api_mapper.normalize import value_kinds
from api_mapper.transforms.inference import TypeFit, TypeFitter

OBSERVED_VALUES_FOR_FULL_TRUST = 5


@dataclass(frozen=True)
class ScoringWeights:
    name: float = 0.45
    string: float = 0.10
    type: float = 0.10
    enum: float = 0.12
    value: float = 0.05
    description: float = 0.08
    structure: float = 0.06
    endpoint: float = 0.04
    context: float = 0.10
    qualifier_agreement: float = 0.08
    value_kind: float = 0.15
    local_nlp: float = 0.20


@dataclass(frozen=True)
class Penalties:
    qualifier_conflict: float = 0.3
    role_mismatch: float = 0.4
    enum_disjoint: float = 0.5
    anchor_missing: float = 0.5
    collection_mismatch: float = 0.5
    shape_conflict: float = 0.6
    fanout: float = 0.9
    per_item_fanout: float = 0.75
    list_to_single: float = 0.7
    modifier_conflict: float = 0.5
    modifier_one_sided: float = 0.8
    deprecated_source: float = 0.9
    guessed_spelling: float = 0.95
    echoed_input: float = 0.85
    unreachable: float = 0.6
    different_record: float = 0.5
    min_name_score: float = 0.3
    min_string_score: float = 0.75


DEFAULT_WEIGHTS = ScoringWeights()
DEFAULT_PENALTIES = Penalties()


class PairScorer:
    def __init__(
        self,
        ctx: SignalContext,
        fitter: TypeFitter,
        weights: ScoringWeights = DEFAULT_WEIGHTS,
        penalties: Penalties = DEFAULT_PENALTIES,
        semantic: SemanticIndex | None = None,
    ):
        self.ctx = ctx
        self.fitter = fitter
        self.weights = weights
        self.penalties = penalties
        self.semantic = semantic
        self.meanings = MeaningMatcher(ctx.lexicon.meaning_rules)

    def score(self, target: FieldProfile, source: FieldProfile, gate: bool = True) -> Candidate | None:
        """Requires lexical, local semantic or purpose support, unless explicitly requested."""
        name_score, name_detail = signals.name_signal(target, source, self.ctx)
        string_score, string_detail = signals.string_signal(target, source)
        lexical_match = name_score >= self.penalties.min_name_score or string_score >= self.penalties.min_string_score
        semantic_score = self.semantic.similarity(target, source) if self.semantic else None
        semantic_match = semantic_score is not None and semantic_score >= self.semantic.settings.min_similarity
        purpose = compare_purposes(target, source)
        expected = value_kinds.expected_kind(target.node)
        seen = value_kinds.observed_kind(source.node)
        value_match = value_kinds.agreement(expected, seen and seen[0])
        if gate and not lexical_match and not semantic_match and not purpose.support and not value_match:
            return None

        fit = self.fitter.fit(target.node, source.node, source.temporal)
        type_score, type_detail = signals.type_signal(fit)
        structure_score, structure_detail = signals.structure_signal(target, source)
        evidence = [
            Evidence(Signal.NAME, name_score, self.weights.name, name_detail),
            Evidence(Signal.SPELLING, string_score, self.weights.string, string_detail),
            Evidence(Signal.TYPE, type_score, self.weights.type, type_detail),
            Evidence(Signal.STRUCTURE, structure_score, self.weights.structure, structure_detail),
        ]
        self._add(evidence, Signal.ENUM, signals.enum_signal(fit, target), self.weights.enum * _enum_trust(source))
        self._add(evidence, Signal.SAMPLE, signals.value_signal(target, source, fit), self.weights.value)
        self._add(
            evidence, Signal.DESCRIPTION, signals.description_signal(target, source, self.ctx), self.weights.description
        )
        self._add(evidence, Signal.ENDPOINT, signals.endpoint_signal(target, source, self.ctx), self.weights.endpoint)
        self._add(evidence, Signal.CONTEXT, signals.context_signal(target, source, self.ctx), self.weights.context)
        evidence.extend(self._penalties(target, source, fit))
        evidence.extend(comparison_evidence(purpose))
        if value_match:
            evidence.append(
                Evidence(
                    Signal.SAMPLE, 1.0, self.weights.value_kind, f"sample values are {seen[0]}s, as the target needs"
                )
            )
        value_veto = None
        if seen and value_kinds.contradiction(expected, seen[0]):
            value_veto = f"sample value {seen[1]!r} is {seen[0]}, not the {expected} the target needs"
            evidence.append(Evidence(Signal.SAMPLE, 0.0, 0.0, value_veto, EvidenceEffect.VETO))
        unmet = self.meanings.unmet_requirements(target, source)
        evidence.extend(Evidence(Signal.ORIGIN_REQUIREMENT, 0.0, 0.0, detail, EvidenceEffect.VETO) for detail in unmet)
        for label, profile in (("Target", target), ("Source", source)):
            evidence.extend(
                Evidence(Signal.DOCUMENTATION_CONTEXT, 1.0, 0.0, f'{label}: {clue.location}: "{clue.text}"')
                for clue in profile.node.documentation
            )
        if (
            purpose.support
            and not purpose.conflicts
            and can_review(target, source, fit, evidence, definition_match=purpose.definition_match)
        ):
            evidence.append(
                Evidence(
                    Signal.CONTEXT_REVIEW,
                    1.0,
                    0.0,
                    "explicit definitions or documented value patterns support a candidate for review; "
                    "lexical score is unchanged",
                )
            )
            if purpose.definition_match:
                evidence.append(
                    Evidence(
                        Signal.DEFINITION_PREFERRED,
                        1.0,
                        0.0,
                        "matching explicit definitions take precedence over name similarity; confirm record selection",
                    )
                )
        if target.node.sample_sources or source.node.sample_sources:
            evidence.append(
                Evidence(
                    Signal.DOCUMENTATION_SAMPLES,
                    1.0,
                    0.0,
                    "documentation response examples supplement declared schemas; "
                    "examples do not prove field meaning or complete value coverage",
                )
            )
        if self.ctx.reachability and self.ctx.reachability.requires_body_review(
            (source.node.api, source.node.endpoint), target.endpoint_inputs
        ):
            evidence.append(
                Evidence(
                    Signal.BODY_CONTEXT,
                    1.0,
                    0.0,
                    "JSON body inputs require confirmed identity binding and caller context",
                )
            )
        if target.roles and "identifier" in target.leaf and "identifier" not in source.leaf:
            evidence.append(
                Evidence(
                    Signal.IDENTITY_REVIEW,
                    1.0,
                    0.0,
                    "a role-qualified identifier needs proof of the referenced record's identity",
                )
            )
        if semantic_score is not None:
            rules_score = _combine(evidence)
            nlp_signal = Evidence(
                Signal.LOCAL_NLP,
                semantic_score,
                self.weights.local_nlp,
                "cosine similarity of local field-name and description embeddings",
            )
            weight = self.weights.local_nlp if _combine([*evidence, nlp_signal]) > rules_score else 0.0
            add_semantic_evidence(
                evidence, target, source, fit, semantic_score, weight, rules_score, semantic_match, lexical_match
            )

        veto = fit.veto or value_veto or next(iter((*purpose.conflicts, *unmet)), None)
        if veto:
            if fit.veto:
                evidence.append(Evidence(Signal.TYPE, 0.0, 0.0, fit.veto, EvidenceEffect.VETO))
            return Candidate(
                source=source.node, score=0.0, evidence=tuple(evidence), transforms=fit.steps, vetoed_by=veto
            )

        return Candidate(
            source=source.node, score=round(_combine(evidence), 4), evidence=tuple(evidence), transforms=fit.steps
        )

    def _penalties(self, target: FieldProfile, source: FieldProfile, fit: TypeFit) -> list[Evidence]:
        found: list[Evidence] = []
        p = self.penalties
        for conflict in self.meanings.conflicts(target, source):
            found.append(self._multiplier(Signal.MEANING, p.qualifier_conflict, conflict))

        relation = signals.qualifier_relation(target, source)
        families = f"{'/'.join(sorted(target.families))} vs {'/'.join(sorted(source.families))}"
        if relation == "agree":
            found.append(
                Evidence(Signal.QUALIFIER, 1.0, self.weights.qualifier_agreement, f"same account family ({families})")
            )
        elif relation == "conflict":
            found.append(
                self._multiplier(Signal.QUALIFIER, p.qualifier_conflict, f"different account family ({families})")
            )

        roles = signals.role_mismatch(target, source)
        if roles:
            found.append(
                self._multiplier(
                    Signal.ROLE, p.role_mismatch, f"role words on one side only: {', '.join(sorted(roles))}"
                )
            )

        modifiers = signals.modifier_difference(target, source, self.ctx)
        if modifiers:
            one_sided = "none" in modifiers
            factor = p.modifier_one_sided if one_sided else p.modifier_conflict
            found.append(self._multiplier(Signal.MODIFIER, factor, f"{modifiers[0]} is not {modifiers[1]}"))

        if not signals.anchored(target, source, self.ctx):
            found.append(
                self._multiplier(
                    Signal.ANCHOR, p.anchor_missing, f"source never mentions {', '.join(sorted(target.anchor))}"
                )
            )

        if not signals.collection_agrees(target, source, self.ctx):
            other = source.collection or source.endpoint_concepts
            found.append(
                self._multiplier(
                    Signal.COLLECTION,
                    p.collection_mismatch,
                    f"items are different things "
                    f"({'/'.join(target.collection or target.endpoint_concepts[-1:])} vs {'/'.join(other)})",
                )
            )

        conflict = signals.shapes_conflict(target, source, fit)
        if conflict:
            found.append(self._multiplier(Signal.SAMPLE, p.shape_conflict, f"incompatible samples: {conflict}"))

        same_record = bool(target.endpoint_inputs & source.endpoint_inputs)
        if source.node.array_depth > target.node.array_depth and not same_record:
            found.append(
                self._multiplier(Signal.LIST_TO_ONE, p.list_to_single, "source is a list; the target holds one value")
            )

        if signals.per_item_fanout(target, source):
            found.append(
                self._multiplier(
                    Signal.FAN_OUT,
                    p.per_item_fanout,
                    "list filled by one detail call per item instead of a list source",
                )
            )
        elif target.node.array_depth > source.node.array_depth:
            found.append(
                self._multiplier(
                    Signal.FAN_OUT, p.fanout, "source sits outside the target's array; repeated into each item"
                )
            )

        if fit.enum_mapping is not None and not fit.enum_mapping.mapping:
            found.append(self._multiplier(Signal.ENUM, p.enum_disjoint, "no enum value in common"))

        guesses = [*target.guesses, *source.guesses]
        if guesses:
            read = ", ".join(f"{token!r} as {word}" for token, word in guesses)
            found.append(self._multiplier(Signal.SPELLING, p.guessed_spelling, f"read {read}"))

        if signals.unreachable(target, source, self.ctx):
            found.append(
                self._multiplier(Signal.REACH, p.unreachable, "cannot be called for the record this request asks about")
            )

        records = signals.different_record(target, source, self.ctx)
        if records:
            found.append(
                self._multiplier(Signal.RECORD, p.different_record, f"describes a {records[1]}, not the {records[0]}")
            )

        if source.echoes_input and target.endpoint_inputs and source.identity not in target.endpoint_inputs:
            found.append(
                self._multiplier(
                    Signal.ECHO, p.echoed_input, "source only repeats an input the upstream request does not have"
                )
            )

        if source.node.deprecated:
            found.append(self._multiplier(Signal.DEPRECATED, p.deprecated_source, "source field is deprecated"))
        return found

    @staticmethod
    def _add(evidence: list[Evidence], signal: Signal, result: signals.SignalResult, weight: float) -> None:
        if result is not None:
            evidence.append(Evidence(signal, result[0], weight, result[1]))

    @staticmethod
    def _multiplier(signal: Signal, factor: float, detail: str) -> Evidence:
        return Evidence(signal, factor, 0.0, detail, EvidenceEffect.MULTIPLIER)


def _enum_trust(source: FieldProfile) -> float:
    """A declared enum is full evidence; a handful of sample values is only partial evidence."""
    if source.node.enum:
        return 1.0
    return min(1.0, len(source.node.observed) / OBSERVED_VALUES_FOR_FULL_TRUST)


def _combine(evidence: list[Evidence]) -> float:
    weighted = [e for e in evidence if e.effect is EvidenceEffect.WEIGHTED]
    total_weight = sum(e.weight for e in weighted)
    score = sum(e.score * e.weight for e in weighted) / total_weight if total_weight else 0.0
    for e in evidence:
        if e.effect is EvidenceEffect.MULTIPLIER:
            score *= e.score
    return score
