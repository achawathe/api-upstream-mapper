import pytest

from api_mapper.models import FieldNode, TransformKind
from api_mapper.transforms.enum_mapping import map_enum_values
from api_mapper.transforms.inference import TypeFitter


@pytest.mark.parametrize(
    ("source", "targets", "expected"),
    [
        ("DDA", ["CHECKING", "SAVINGS"], "CHECKING"),
        ("SAV", ["CHECKING", "SAVINGS"], "SAVINGS"),
        ("MMA", ["CHECKING", "MONEYMARKET"], "MONEYMARKET"),
        ("ACH", ["US_ACH", "US_RTP"], "US_ACH"),
        ("POA", ["POWER_OF_ATTORNEY", "PRIMARY"], "POWER_OF_ATTORNEY"),
        ("PDNG", ["PENDING", "POSTED"], "PENDING"),
        ("BOOKED", ["PENDING", "POSTED"], "POSTED"),
        ("D", ["CREDIT", "DEBIT", "MEMO"], "DEBIT"),
        ("CHARGE_CARD", ["CHARGE", "CREDITCARD"], "CHARGE"),
        ("ACTIVE", ["OPEN", "CLOSED"], "OPEN"),
    ],
)
def test_enum_rules(lexicon, source, targets, expected):
    assert map_enum_values([source], targets, lexicon).mapping == {source: expected}


def test_ambiguous_enum_values_stay_unmapped(lexicon):
    result = map_enum_values(["JOINT", "P"], ["PRIMARY_JOINT", "SECONDARY_JOINT", "PENDING", "POSTED"], lexicon)
    assert result.unmapped == ("JOINT", "P")


def _node(type_, **kwargs):
    return FieldNode(api="a", endpoint="GET /x", path=kwargs.pop("path", "f"), type=type_, **kwargs)


@pytest.fixture
def fitter(lexicon):
    return TypeFitter(lexicon)


def test_minor_units(fitter):
    fit = fitter.fit(_node("number"), _node("integer", description="Amount in minor units (cents)."), False)
    assert [s.kind for s in fit.steps] == [TransformKind.MINOR_UNITS_TO_DECIMAL]


def test_epoch_millis_to_date_time(fitter):
    fit = fitter.fit(_node("string", format="date-time"), _node("integer", example=1760572800000), True)
    assert [s.kind for s in fit.steps] == [TransformKind.EPOCH_MILLIS_TO_DATETIME]


def test_compact_date(fitter):
    fit = fitter.fit(_node("string", format="date"), _node("string", example="20261115"), True)
    assert [s.kind for s in fit.steps] == [TransformKind.COMPACT_DATE_TO_ISO]


@pytest.mark.parametrize(
    ("target", "source"),
    [
        (_node("string", format="date"), _node("boolean")),
        (_node("string", format="date"), _node("integer")),
        (_node("number"), _node("string", format="date")),
        (_node("integer"), _node("boolean")),
    ],
)
def test_incompatible_types_are_vetoed(fitter, target, source):
    assert fitter.fit(target, source, False).veto
