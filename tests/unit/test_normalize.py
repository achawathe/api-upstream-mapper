import pytest

from api_mapper.models import FieldNode
from api_mapper.normalize.profiler import Profiler
from api_mapper.normalize.tokenizer import singularize, split_identifier


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("debitAccount.id", ("debit", "account", "id")),
        ("IBANNumber", ("iban", "number")),
        ("int_rate_pct", ("int", "rate", "pct")),
        ("address-line-2", ("address", "line", "2")),
    ],
)
def test_split_identifier(text, tokens):
    assert split_identifier(text) == tokens


@pytest.mark.parametrize(
    ("word", "singular"),
    [("balances", "balance"), ("entries", "entry"), ("addresses", "address"), ("status", "status"), ("ids", "id")],
)
def test_singularize(word, singular):
    assert singularize(word) == singular


@pytest.mark.parametrize(
    ("name", "concepts"),
    [
        ("acct_no", ("account", "number")),
        ("ledgerBal", ("current", "balance")),
        ("creditLine", ("credit", "limit")),
        ("interestPaidYearToDate", ("interest", "paid", "ytd")),
        ("givenName", ("first",)),
        ("zip", ("postalcode",)),
        ("chequeNo", ("checknumber",)),
    ],
)
def test_lexicon_concepts(lexicon, name, concepts):
    assert lexicon.concepts(name) == concepts


def test_families_and_roles(lexicon):
    assert lexicon.family_of(lexicon.concepts("LineOfCreditAccount")) == {"credit"}
    assert lexicon.family_of(lexicon.concepts("debitAccount")) == {"deposit"}
    assert lexicon.roles_of(lexicon.concepts("fromAccountId")) == {"from"}


def test_profile_uses_parent_when_leaf_is_generic(lexicon):
    node = FieldNode(api="a", endpoint="GET /x", path="debitAccount.id", type="string")
    profile = Profiler(lexicon).profile(node, frozenset(), ("deposit",))
    assert profile.bag == {"identifier": 1.0, "debit": 1.0, "account": 1.0}
    assert profile.qualifiers == {"deposit"}
    assert profile.anchor == {"identifier"}


def test_profile_collection_skips_wrapper_segments(lexicon):
    node = FieldNode(api="a", endpoint="GET /x", path="data[].account.type", type="string", array_depth=1)
    profile = Profiler(lexicon).profile(node, frozenset(), ("account",))
    assert profile.collection == ("account",)
