"""Origin requirements survive misleading names, matching samples and perfect embeddings."""

import pytest

from api_mapper.matching.engine import MatchingEngine
from api_mapper.models import FieldNode, MappingStatus
from api_mapper.normalize.profiler import Profiler
from tests.unit.test_semantic import Encoder


def profile(lexicon, api, path, **kwargs):
    node = FieldNode(api=api, endpoint="GET /accounts", path=path, type=kwargs.pop("type", "string"), **kwargs)
    return Profiler(lexicon).profile(node, frozenset(), ("account",))


@pytest.mark.parametrize("nlp", [False, True])
@pytest.mark.parametrize(
    ("target", "source"),
    [
        ({"path": "transactionTimestamp", "format": "date-time"}, {"path": "transactionInformation"}),
        ({"path": "priorRate", "type": "number"}, {"path": "previous", "format": "uri"}),
        ({"path": "accountNumberDisplay", "example": "1234"}, {"path": "accountId", "example": "1234"}),
        ({"path": "foreignCurrency"}, {"path": "currency"}),
        (
            {
                "path": "subCategory",
                "description": "Classification specifying the standard of the transaction category.",
            },
            {"path": "detailedCategory", "description": "A granular category conveying the transaction intent."},
        ),
        (
            {"path": "referenceTransactionId", "description": "The identity of the transaction being reversed."},
            {"path": "transactionReference", "description": "Unique reference for the transaction."},
        ),
    ],
)
def test_unsupported_origins_are_not_selected(lexicon, nlp, target, source):
    target = profile(lexicon, "up", **target)
    source = profile(lexicon, "down", **source)
    engine = MatchingEngine(lexicon, encoder=Encoder() if nlp else None)
    candidate = engine.prepare([target], [source]).score_pair(target.node.key, source.node.key)
    assert candidate.vetoed_by
    assert engine.match([target], [source])[0].chosen is None


@pytest.mark.parametrize(
    ("target", "source"),
    [
        ({"path": "accountNumberDisplay"}, {"path": "mask"}),
        ({"path": "foreignCurrency"}, {"path": "foreignCurrencyCode"}),
        (
            {
                "path": "subCategory",
                "description": "Classification specifying the standard of the transaction category.",
            },
            {"path": "categorySystem", "description": "The classification standard name."},
        ),
        (
            {"path": "referenceTransactionId", "description": "The identity of the transaction being reversed."},
            {
                "path": "pendingTransactionId",
                "description": "The ID of a posted transaction's associated pending transaction.",
            },
        ),
    ],
)
def test_supported_origin_is_not_vetoed(lexicon, target, source):
    target = profile(lexicon, "up", **target)
    source = profile(lexicon, "down", **source)
    candidate = MatchingEngine(lexicon).prepare([target], [source]).score_pair(target.node.key, source.node.key)
    assert candidate.vetoed_by is None


def test_explicit_status_origin_can_require_unresolved_enum_conversion(lexicon):
    target = profile(lexicon, "up", "status", description="Account status.", enum=("OPEN", "CLOSED"))
    source = profile(
        lexicon,
        "down",
        "x8",
        description="Specifies the status of account resource in code form.",
        enum=("Enabled", "Deleted"),
    )
    decoy = profile(lexicon, "down", "switchStatus", description="Specifies the switch status for the account.")
    mapping = MatchingEngine(lexicon).match([target], [source, decoy])[0]
    assert mapping.chosen.source.key == source.node.key
    assert mapping.status is MappingStatus.REVIEW
    assert mapping.chosen.score < 0.5
    assert any("enum" in note for note in mapping.notes)
    assert mapping.chosen.transforms[0].params["mapping"] == {}
