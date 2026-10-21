"""A planned map selector must read the requested entry during mock validation."""

import asyncio

import pytest

from api_mapper.models import ApiSpec, Endpoint, Parameter, SpecKind
from api_mapper.pipeline.orchestrator import MappingPipeline, PipelineInputs
from api_mapper.validation.assembler import extract
from api_mapper.validation.executor import PlanExecutor
from api_mapper.validation.mock_downstream import MockDownstreams
from tests.conftest import SAMPLES

BENCHMARK = SAMPLES / "benchmarks" / "value-keys"


@pytest.fixture(scope="module")
def run(lexicon):
    pipeline = MappingPipeline(lexicon)
    return pipeline.run(
        pipeline.load(BENCHMARK / "upstream.yaml", sorted(BENCHMARK.glob("downstream/*/manifest.yaml")))
    ).run


def execute(run, lexicon, endpoint, params, include_review=True):
    executor = PlanExecutor(run, MockDownstreams(run.downstreams, lexicon), include_review=include_review)
    return asyncio.run(executor.execute(endpoint, params))


@pytest.mark.parametrize("city, temperature", [("toronto", 12.5), ("vancouver", 9.1)])
def test_weather_reads_the_city_requested(run, lexicon, city, temperature):
    result = execute(run, lexicon, "GET /cities/{city}/weather", {"city": city})
    assert result.body == {"city": city, "temperature": temperature, "observedAt": "2026-10-20T12:00:00Z"}
    assert not result.issues and not result.warnings


def test_currency_selection_reads_the_requested_rate(run, lexicon):
    result = execute(run, lexicon, "GET /rates/{currency}", {"currency": "CAD"})
    assert result.body == {"rate": 1.37, "asOf": "2026-10-19"}
    assert not result.issues and not result.warnings


def test_unresolved_map_selector_can_be_supplied_by_caller_context(run, lexicon):
    result = execute(
        run,
        lexicon,
        "GET /accounts/{accountId}/balance",
        {"accountId": "ACC-2002", "customerId": "CUS-1", "map key:balances": "ACC-2002"},
    )
    assert result.body["currentBalance"] == 80.0
    assert result.body["availableBalance"] == 80.0
    assert not result.issues and not result.warnings
    assert all("CUS-1" in c.url and "ACC-2002" not in c.url for c in result.calls)


@pytest.mark.parametrize("params, message", [({}, "select an entry"), ({"city": "missing-city"}, "not found")])
def test_missing_or_unknown_map_keys_report_issues(run, lexicon, params, message):
    result = execute(run, lexicon, "GET /cities/{city}/weather", params)
    assert "temperature" not in result.body and "city" not in result.body
    assert any(message in issue.message for issue in result.issues)


def test_maps_awaiting_review_are_not_used_when_review_is_disabled(run, lexicon):
    result = execute(run, lexicon, "GET /cities/{city}/weather", {"city": "toronto"}, include_review=False)
    assert "temperature" not in result.body and "city" not in result.body
    assert not result.issues


def test_nested_map_keys_preserve_dots_in_data_and_array_shape():
    document = {"groups": [{"rates": {"CA.ON": {"values": {"CAD": 1.37}}}}]}
    selected = {"groups[].rates": "CA.ON", "groups[].rates.{key}.values": "CAD"}
    assert extract(document, "groups[].rates.{key}.values.{key}", selected) == [1.37]
    assert extract(document, "groups[].rates.@key", selected) == ["CA.ON"]


def test_root_map_selection():
    assert extract({"a.b": 12.5}, "{key}", {"": "a.b"}) == 12.5
    assert extract({"a.b": 12.5}, "@key", {"": "a.b"}) == "a.b"


def test_map_values_containing_arrays_keep_their_array_shape():
    assert extract({"readings": {"toronto": [12.5, 13.1]}}, "readings.{key}[]", {"readings": "toronto"}) == [12.5, 13.1]


def test_nested_map_call_plan_selects_both_entries(lexicon):
    number = {"type": "number"}
    upstream = ApiSpec(
        "up",
        "Weather",
        "1",
        SpecKind.OPENAPI_3,
        "test",
        endpoints=(
            Endpoint(
                "GET",
                "/regions/{region}/cities/{city}/weather",
                "weather",
                parameters=tuple(Parameter(name, "path", True, {"type": "string"}) for name in ("region", "city")),
                response_schema={"type": "object", "properties": {"temperature": number}},
            ),
        ),
    )
    cities = {"type": "object", "additionalProperties": number}
    regions = {"type": "object", "additionalProperties": {"type": "object", "properties": {"cities": cities}}}
    downstream = ApiSpec(
        "down",
        "Weather",
        "1",
        SpecKind.OPENAPI_3,
        "test",
        endpoints=(
            Endpoint(
                "GET",
                "/weather",
                "snapshot",
                response_schema={"type": "object", "properties": {"regions": regions}},
                response_examples=({"regions": {"CA.ON": {"cities": {"Toronto.Centre": 12.5, "Ottawa": 8.4}}}},),
            ),
        ),
    )
    run = MappingPipeline(lexicon).run(PipelineInputs(upstream, (downstream,))).run
    bindings = run.call_plans[0].steps[0].bindings
    assert {(b.parameter, b.reference) for b in bindings} == {("regions", "region"), ("regions.{key}.cities", "city")}
    result = execute(run, lexicon, upstream.endpoints[0].key, {"region": "CA.ON", "city": "Toronto.Centre"})
    assert result.body == {"temperature": 12.5}
    assert not result.issues and not result.warnings
