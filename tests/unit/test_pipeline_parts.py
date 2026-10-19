"""Call planning, error mapping and overrides on the sample run."""

import pytest

from api_mapper.models import BindingSource, MappingStatus, Override, OverrideAction
from tests.helpers import run_sample

ROUTING = "routing|GET /payments/routing/{acctNum}|"


@pytest.fixture(scope="module")
def result(lexicon):
    return run_sample(lexicon)


def _plan(result, endpoint):
    return next(p for p in result.run.call_plans if p.upstream_endpoint == endpoint)


def test_planner_adds_a_call_that_only_supplies_an_input(result):
    plan = _plan(result, "GET /accounts/{accountId}/payment-networks")
    routing = next(s for s in plan.steps if s.api == "routing")
    binding = routing.bindings[0]
    assert binding.source is BindingSource.PRIOR_STEP
    assert binding.reference.endswith("-> account.number")
    supplier = plan.steps[binding.from_step - 1]
    assert supplier.endpoint == "GET /v2/accounts/{accountId}" and supplier.supplies_only_inputs


def test_planner_fans_out_over_array_inputs(result):
    plan = _plan(result, "GET /accounts/{accountId}/contact")
    party = next(s for s in plan.steps if s.endpoint == "GET /parties/{partyId}")
    assert party.is_fanout
    assert party.bindings[0].reference.endswith("holders[].partyId")


def test_planner_reports_inputs_nobody_supplies(result):
    plan = _plan(result, "GET /customers/current")
    assert plan.unresolved_inputs == ("parties GET /parties/{partyId}: partyId",)


def test_conditional_calls_are_tied_to_variants(result):
    plan = _plan(result, "GET /accounts/{accountId}")
    cards = next(s for s in plan.steps if s.api == "cards")
    assert cards.variants == ("LineOfCreditAccount",)


def test_error_mapping(result):
    by_code = {(e.downstream.api, e.downstream.code): e for e in result.run.error_mappings}
    assert by_code[("ledger", "INVALID_RANGE")].upstream_code == "703"
    assert by_code[("deposits", "1004")].upstream_code == "705"
    assert by_code[("core-accounts", "ACCT_CLOSED")].upstream_status == "409"
    assert by_code[("deposits", "1007")].upstream_code == "706"
    routing_outage = next(e for e in result.run.error_mappings if e.downstream.api == "routing" and e.downstream.http_status == "502")
    assert routing_outage.upstream_status == "503"


def test_overrides_choose_reject_and_report_stale(lexicon, result):
    target = next(m for m in result.run.mappings if m.target.path == "paymentNetworks[].bankId")
    overrides = [
        Override(target.target.key, OverrideAction.CHOOSE, f"{ROUTING}routing.wire", note="wire routing preferred"),
        Override("upstream|GET /gone|x", OverrideAction.ACCEPT),
    ]
    rerun = run_sample(lexicon, overrides=overrides).run
    chosen = next(m for m in rerun.mappings if m.target.key == target.target.key)
    assert chosen.status is MappingStatus.MANUAL
    assert chosen.chosen.source.path == "routing.wire"
    assert any("no longer exists" in w for w in rerun.warnings)

    rejected = run_sample(lexicon, overrides=[Override(target.target.key, OverrideAction.REJECT)]).run
    assert next(m for m in rejected.mappings if m.target.key == target.target.key).status is MappingStatus.REJECTED
