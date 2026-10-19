"""The mock harness: executes call plans against fake downstreams built from the specs."""

import asyncio

import pytest

from api_mapper.models import TransformKind, TransformStep
from api_mapper.transforms.apply import TransformError, apply_transforms
from api_mapper.validation.executor import PlanExecutor
from api_mapper.validation.mock_downstream import FaultPlan, MockDownstreams
from tests.helpers import run_sample


@pytest.fixture(scope="module")
def run(lexicon):
    return run_sample(lexicon).run


def _execute(run, lexicon, endpoint, params, faults=None, include_review=True, hint=None):
    executor = PlanExecutor(run, MockDownstreams(run.downstreams, lexicon, faults), include_review=include_review)
    return asyncio.run(executor.execute(endpoint, params, hint))


def test_list_items_are_routed_to_their_own_variant(run, lexicon):
    result = _execute(run, lexicon, "GET /accounts", {})
    categories = [item["accountCategory"] for item in result.body["accounts"]]
    types = [item["accountType"] for item in result.body["accounts"]]
    assert categories == ["DEPOSIT_ACCOUNT", "LOC_ACCOUNT"]
    assert types == ["CHECKING", "CREDITCARD"]
    assert result.issues == []


def test_variant_specific_calls_are_skipped_when_data_rules_them_out(run, lexicon):
    result = _execute(run, lexicon, "GET /accounts/{accountId}", {"accountId": "ACC-1"})
    called = {c.api for c in result.calls}
    assert result.variants == ["DepositAccount"]
    assert "deposits" in called and "cards" not in called and "loans" not in called
    assert result.body["currentBalance"] == 1399.02


def test_chained_call_and_enum_inferred_from_samples(run, lexicon):
    result = _execute(run, lexicon, "GET /accounts/{accountId}/payment-networks", {"accountId": "ACC-1"})
    routing_call = next(c for c in result.calls if c.api == "routing")
    assert routing_call.url.endswith("/payments/routing/000123456789")
    networks = result.body["paymentNetworks"]
    assert networks[0]["type"] == "US_ACH"
    assert "type" not in networks[1]
    assert any("paymentNetworks[1].type" in issue.message and "WIRE" in issue.message for issue in result.issues)


def test_fan_out_calls_once_per_holder(run, lexicon):
    result = _execute(run, lexicon, "GET /accounts/{accountId}/contact", {"accountId": "ACC-1"})
    party_calls = [c for c in result.calls if c.endpoint == "GET /parties/{partyId}"]
    assert len(party_calls) == len(result.body["holders"]) == 2


def test_epoch_and_minor_units_are_converted(run, lexicon):
    result = _execute(run, lexicon, "GET /accounts/{accountId}/transactions", {"accountId": "ACC-1"}, hint="DEPOSIT_ACCOUNT")
    first = result.body["transactions"][0]
    assert first["amount"] == 400.0
    assert first["postedTimestamp"] == "2025-10-17T00:00:00.000Z"
    assert first["debitCreditMemo"] == "DEBIT"


def test_downstream_failure_becomes_the_mapped_upstream_error(run, lexicon):
    result = _execute(run, lexicon, "GET /accounts/{accountId}", {"accountId": "ACC-1"}, FaultPlan(statuses={"deposits": 409}))
    assert result.status == 409
    assert result.body["code"] == "705"


def test_independent_calls_run_concurrently(run, lexicon):
    result = _execute(run, lexicon, "GET /accounts/{accountId}/contact", {"accountId": "ACC-1"}, FaultPlan(latency_ms=30))
    assert result.elapsed_ms < result.sequential_ms


def test_unresolved_inputs_come_from_caller_context(run, lexicon):
    result = _execute(run, lexicon, "GET /customers/current", {"partyId": "PTY-9"})
    assert result.body == {"customerId": "PTY-9"}


def test_transform_application():
    assert apply_transforms((TransformStep(TransformKind.COMPACT_DATE_TO_ISO, ""),), "20510801") == "2051-08-01"
    assert apply_transforms((TransformStep(TransformKind.MINOR_UNITS_TO_DECIMAL, "", {"exponent": 2}),), 139902) == 1399.02
    with pytest.raises(TransformError):
        apply_transforms((TransformStep(TransformKind.ENUM_MAP, "", {"mapping": {"D": "DEBIT"}}),), "X")


def test_nested_arrays_round_trip():
    from api_mapper.validation.assembler import extract, write

    document = {"matrix": [[1, 2], [3]]}
    values = extract(document, "matrix[].[]")
    rebuilt: dict = {}
    write(rebuilt, "grid[].[]", values)
    assert rebuilt == {"grid": [[1, 2], [3]]}
