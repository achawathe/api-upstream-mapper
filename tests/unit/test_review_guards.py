"""Regressions for semantic recovery and evidence required by automatic decisions."""

from dataclasses import replace

import pytest

from api_mapper.matching.assigner import Thresholds, assign
from api_mapper.matching.engine import MatchingEngine
from api_mapper.models import Candidate, Evidence, FieldNode, MappingStatus
from api_mapper.normalize.profiler import Profiler
from tests.unit.test_semantic import Encoder


def pair(lexicon, target, source):
    profiler = Profiler(lexicon)
    return [profiler.profile(node, frozenset(), ()) for node in (target, source)]


def test_weak_similarity_does_not_dilute_rule_confidence(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "accountId", "string"),
        FieldNode("down", "GET /x", "accountId", "string", description="opaque identifier"),
    )
    rules = MatchingEngine(lexicon).prepare([target], [source]).score_all()[target.node.key][0]
    local = MatchingEngine(lexicon, encoder=Encoder([[1, 0], [0, 1]])).prepare([target], [source])
    candidate = local.score_all()[target.node.key][0]
    assert candidate.score == rules.score
    assert next(e for e in candidate.evidence if e.signal == "local_nlp").weight == 0


def test_semantic_description_can_surface_an_opaque_field_for_review(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "airPressure", "number", description="Atmospheric pressure"),
        FieldNode("down", "GET /x", "b42", "number", description="Atmospheric pressure"),
    )
    assert MatchingEngine(lexicon).match([target], [source])[0].status is MappingStatus.UNMAPPED
    mapping = MatchingEngine(lexicon, encoder=Encoder()).match([target], [source])[0]
    assert mapping.status is MappingStatus.REVIEW
    assert mapping.chosen.source == source.node
    assert any(e.signal == "anchor" for e in mapping.chosen.evidence)
    assert any(e.signal == "semantic_review" for e in mapping.chosen.evidence)


@pytest.mark.parametrize("path,depth", [("fromAccountId", 0), ("transfers[].accountId", 1)])
def test_semantic_fallback_does_not_bypass_role_or_array_conflicts(lexicon, path, depth):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "accountId", "string", description="Account identity"),
        FieldNode("down", "GET /x", path, "string", description="Account identity", array_depth=depth),
    )
    candidate = MatchingEngine(lexicon, encoder=Encoder()).prepare([target], [source]).score_all()[target.node.key][0]
    assert not any(e.signal == "semantic_review" for e in candidate.evidence)
    assert assign([target], {target.node.key: [candidate]})[0].status is not MappingStatus.AUTO


def test_semantic_promotion_cannot_cross_automatic_threshold(lexicon):
    target, source = pair(
        lexicon, FieldNode("up", "GET /x", "code", "string"), FieldNode("down", "GET /x", "code", "string")
    )
    candidate = Candidate(source.node, 0.8, (Evidence("rules_score", 0.6, 0, "before NLP"),))
    assert assign([target], {target.node.key: [candidate]})[0].status is MappingStatus.REVIEW


def test_unproven_numeric_cast_requires_review(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "temperature", "number"),
        FieldNode("down", "GET /x", "temperature", "string"),
    )
    assert MatchingEngine(lexicon).match([target], [source])[0].status is MappingStatus.REVIEW
    numeric = replace(source, node=replace(source.node, example="23.5"))
    assert MatchingEngine(lexicon).match([target], [numeric])[0].status is MappingStatus.AUTO


def test_extra_array_levels_require_item_selection_even_with_high_score(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "rate", "number"),
        FieldNode("down", "GET /x", "rates[].rate", "number", array_depth=1),
    )
    candidate = Candidate(source.node, 0.99, ())
    mapping = assign([target], {target.node.key: [candidate]})[0]
    assert mapping.status is MappingStatus.REVIEW
    assert "which item" in mapping.notes[0]


def test_related_record_id_is_not_a_generic_reference(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "referenceTransactionId", "string"),
        FieldNode("down", "GET /x", "TransactionReference", "string"),
    )
    mapping = MatchingEngine(lexicon).match([target], [source])[0]
    assert mapping.status is MappingStatus.UNMAPPED
    assert any(e.signal == "origin_requirement" for c in mapping.alternatives for e in c.evidence)


def test_plain_text_cannot_be_an_automatic_timestamp(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "transactionTimestamp", "string", format="date-time"),
        FieldNode("down", "GET /x", "transactionTimestamp", "string"),
    )
    assert MatchingEngine(lexicon).match([target], [source])[0].status is MappingStatus.REVIEW


def test_broad_enum_is_not_an_automatic_detailed_type(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "accountType", "string", enum=("CHECKING", "SAVINGS", "INVESTMENT")),
        FieldNode(
            "down", "GET /x", "accountType", "string", enum=("depository", "credit", "loan", "other", "investment")
        ),
    )
    mapping = MatchingEngine(lexicon).match([target], [source])[0]
    assert mapping.status is MappingStatus.REVIEW
    assert any("most source enum" in note for note in mapping.notes)


def test_semantic_fallback_respects_a_stricter_review_threshold(lexicon):
    target, source = pair(
        lexicon,
        FieldNode("up", "GET /x", "airPressure", "number", description="Atmospheric pressure"),
        FieldNode("down", "GET /x", "b42", "number", description="Atmospheric pressure"),
    )
    engine = MatchingEngine(
        lexicon, thresholds=Thresholds(auto=0.99, review=0.95), encoder=Encoder([[1, 0], [0.9, 0.19**0.5]])
    )
    assert engine.match([target], [source])[0].status is MappingStatus.UNMAPPED
