"""Spec-less APIs whose JSON keys are data, with decoys; see samples/benchmarks/value-keys."""

import pytest

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import Outcome, grade
from api_mapper.models import BindingSource, MappingStatus
from api_mapper.pipeline.orchestrator import MappingPipeline
from tests.conftest import SAMPLES

BENCHMARK = SAMPLES / "benchmarks" / "value-keys"


@pytest.fixture(scope="module")
def run(lexicon):
    pipeline = MappingPipeline(lexicon)
    return pipeline.run(
        pipeline.load(BENCHMARK / "upstream.yaml", sorted(BENCHMARK.glob("downstream/*/manifest.yaml")))
    ).run


def test_no_wrong_automatic_mapping_and_decoys_never_chosen(run):
    report = grade(run.mappings, load_answer_key(BENCHMARK / "answer_key.yaml", run.upstream.name))
    assert report.counts[Outcome.WRONG_AUTO] + report.counts[Outcome.SPURIOUS_AUTO] == 0, report.failures()
    assert report.recall == 1.0, report.summary()
    temperature = next(m for m in run.mappings if m.target.path == "temperature")
    assert temperature.chosen.source.path == "snapshot.weather.city.{key}"
    assert any("shared weather context" in note for note in temperature.notes)
    chosen = {m.chosen.source.path for m in run.mappings if m.chosen}
    assert not chosen & {"cpu.temp", "station.tempSensorId"}
    sensor = next(c for c in temperature.alternatives if c.source.path == "station.tempSensorId")
    assert sensor.vetoed_by == "sample value 'TS-104' is text, not the number the target needs"


def test_map_sources_wait_for_review_with_the_entry_to_choose(run):
    from_maps = [m for m in run.mappings if m.chosen and m.chosen.source.map_path]
    assert from_maps and all(m.status is MappingStatus.REVIEW for m in from_maps)
    assert all(any("whose keys are data" in note for note in m.notes) for m in from_maps)


def test_call_plan_binds_the_map_key_by_name_or_by_value_kind(run):
    bindings = {
        plan.upstream_endpoint: [b for step in plan.steps for b in step.bindings if b.location == "map key"]
        for plan in run.call_plans
    }
    weather = bindings["GET /cities/{city}/weather"]
    assert [(b.parameter, b.source, b.reference) for b in weather] == [
        ("snapshot.weather.city", BindingSource.UPSTREAM_REQUEST, "city")
    ]
    rates = bindings["GET /rates/{currency}"]
    assert [(b.source, b.reference) for b in rates] == [(BindingSource.UPSTREAM_REQUEST, "currency")]
    assert [b.source for b in bindings["GET /accounts/{accountId}/balance"]] == [BindingSource.UNRESOLVED]


def test_account_balance_does_not_use_an_account_id_as_a_customer_id(run):
    plan = next(p for p in run.call_plans if p.upstream_endpoint == "GET /accounts/{accountId}/balance")
    customer = next(b for step in plan.steps for b in step.bindings if b.parameter == "customerId")
    assert customer.source is BindingSource.UNRESOLVED
    assert "account-balances GET /customers/{customerId}/balances: customerId" in plan.unresolved_inputs
