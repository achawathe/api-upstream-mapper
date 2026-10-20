"""Sample values support or contradict a match by the kind of data they hold; they never make one alone."""

import pytest

from api_mapper.models import FieldNode
from api_mapper.normalize import value_kinds as vk


def node(type_="string", fmt=None, description="", observed=(), example=None):
    return FieldNode(
        "api", "GET /x", "f", type_, format=fmt, description=description, observed=observed, example=example
    )


@pytest.mark.parametrize(
    ("field", "kind"),
    [
        (node(fmt="date-time"), vk.DATE_TIME),
        (node(description="ISO 4217 currency code."), vk.CURRENCY),
        (node(description="The currency code of the balance."), vk.CURRENCY),
        (node("number"), vk.NUMBER),
        (node(description="Name of the city."), None),
    ],
)
def test_expected_kind_comes_from_format_type_and_definition(field, kind):
    assert vk.expected_kind(field) == kind


def test_observed_kind_needs_every_value_to_agree():
    assert vk.observed_kind(node(observed=("EUR", "CAD"))) == (vk.CURRENCY, "EUR")
    assert vk.observed_kind(node(observed=("2026-10-20", "2026-10-20T12:00:00Z")))[0] == vk.DATE_TIME
    assert vk.observed_kind(node(observed=("EUR", "Toronto"))) is None
    assert vk.observed_kind(node()) is None
    assert vk.observed_kind(node("number", example=12.5)) == (vk.NUMBER, 12.5)


def test_contradictions_and_agreement():
    assert vk.contradiction(vk.NUMBER, vk.TEXT)
    assert vk.contradiction(vk.CURRENCY, vk.TEXT)
    assert vk.contradiction(vk.DATE, vk.CURRENCY)
    assert not vk.contradiction(vk.DATE, vk.NUMBER), "epoch numbers are handled by the type fit"
    assert not vk.contradiction(None, vk.TEXT)
    assert vk.agreement(vk.DATE, vk.DATE_TIME)
    assert not vk.agreement(vk.NUMBER, vk.NUMBER), "numbers are too common to say anything about meaning"
