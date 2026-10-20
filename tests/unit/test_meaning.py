"""Domain definitions disambiguate similar words without treating embeddings as proof."""

import pytest

from api_mapper.matching.engine import MatchingEngine
from api_mapper.matching.meaning import MeaningMatcher
from api_mapper.models import FieldNode
from api_mapper.normalize.definitions import leading_definition
from api_mapper.normalize.profiler import Profiler
from tests.unit.test_semantic import Encoder


def _profile(lexicon, name, description=""):
    node = FieldNode(api="test", endpoint="GET /transactions", path=name, type="string", description=description)
    return Profiler(lexicon).profile(node, frozenset(), ())


@pytest.mark.parametrize(
    ("left", "right", "group"),
    [
        (
            ("postedTimestamp", ""),
            ("authorized_datetime", "Date when the transaction was posted."),
            "transaction_event",
        ),
        (("bookingDate", ""), ("valueDate", ""), "transaction_event"),
        (("transactionTimestamp", "Date added to the server."), ("postedDate", ""), "transaction_event"),
        (("payeeName", ""), ("merchantId", ""), "value_kind"),
        (("productName", "Marketed product."), ("products", "Products enabled for the Item."), "product_kind"),
        (("category", "Merchant category code."), ("category_id", ""), "classification_system"),
        (("isoCurrencyCode", ""), ("unofficial_currency_code", ""), "currency_standard"),
        (("foreignCurrency", ""), ("accountCurrency", ""), "currency_role"),
    ],
)
def test_explicit_different_meanings_conflict(lexicon, left, right, group):
    conflicts = MeaningMatcher(lexicon.meaning_rules).conflicts(_profile(lexicon, *left), _profile(lexicon, *right))
    assert any(item.startswith(group + ":") for item in conflicts)


def test_unknown_definition_is_not_inferred_from_similar_name(lexicon):
    matcher = MeaningMatcher(lexicon.meaning_rules)
    assert matcher.conflicts(_profile(lexicon, "eventDate"), _profile(lexicon, "postedDate")) == []
    assert matcher.conflicts(_profile(lexicon, "bookingDate"), _profile(lexicon, "postedDate")) == []


def test_definition_discards_markup_and_later_examples():
    text = "<b>Date</b> when [assets](https://example.org/posted-date) become available. Example: posted date."
    assert leading_definition(text) == "Date when assets become available."


def test_identical_embeddings_do_not_remove_meaning_penalty(lexicon):
    target = _profile(lexicon, "postedTimestamp")
    wrong = _profile(lexicon, "authorizedTimestamp")
    right = _profile(lexicon, "bookingTimestamp")
    prepared = MatchingEngine(lexicon, encoder=Encoder()).prepare([target], [wrong, right])
    wrong_score = prepared.score_pair(target.node.key, wrong.node.key)
    right_score = prepared.score_pair(target.node.key, right.node.key)
    assert any(e.signal == "meaning" and e.score < 1 for e in wrong_score.evidence)
    assert not any(e.signal == "meaning" for e in right_score.evidence)
    assert wrong_score.score < right_score.score
