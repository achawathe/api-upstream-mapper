"""Call inputs must identify the same resource, not merely share an identifier word."""

import asyncio

import pytest

from api_mapper.models import (
    ApiSpec,
    BindingSource,
    Candidate,
    Endpoint,
    FieldMapping,
    FieldNode,
    MappingRun,
    MappingStatus,
    Parameter,
    SpecKind,
)
from api_mapper.planning.call_planner import CallPlanner
from api_mapper.validation.executor import PlanExecutor
from api_mapper.validation.mock_downstream import MockDownstreams


def planned_run(lexicon, upstream_path, upstream_name, downstream_path, downstream_name):
    upstream_endpoint = Endpoint(
        "GET", upstream_path, "up", parameters=(Parameter(upstream_name, "path", True, {"type": "string"}),)
    )
    downstream_endpoint = Endpoint(
        "GET",
        downstream_path,
        "down",
        parameters=(Parameter(downstream_name, "path", True, {"type": "string"}),),
        response_schema={"type": "object", "properties": {"balance": {"type": "number"}}},
    )
    upstream = ApiSpec("up", "up", "1", SpecKind.OPENAPI_3, "up", endpoints=(upstream_endpoint,))
    downstream = ApiSpec("down", "down", "1", SpecKind.OPENAPI_3, "down", endpoints=(downstream_endpoint,))
    mapping = FieldMapping(
        target=FieldNode("up", upstream_endpoint.key, "balance", "number"),
        status=MappingStatus.REVIEW,
        chosen=Candidate(FieldNode("down", downstream_endpoint.key, "balance", "number"), 0.8, ()),
    )
    plans = CallPlanner(lexicon, upstream, (downstream,), []).plan([mapping])
    return MappingRun(upstream, (downstream,), [mapping], call_plans=plans)


def plan_binding(lexicon, *args):
    return planned_run(lexicon, *args).call_plans[0]


@pytest.mark.parametrize(
    ("upstream_path", "upstream_name", "downstream_path", "downstream_name"),
    [
        ("/accounts/{accountId}", "accountId", "/customers/{customerId}/balances", "customerId"),
        ("/accounts/{id}", "id", "/customers/{id}/balances", "id"),
        ("/customers/{customerId}", "customerId", "/accounts/{accountId}", "accountId"),
    ],
)
def test_unrelated_resource_ids_remain_unresolved(
    lexicon, upstream_path, upstream_name, downstream_path, downstream_name
):
    plan = plan_binding(lexicon, upstream_path, upstream_name, downstream_path, downstream_name)
    assert plan.steps[0].bindings[0].source is BindingSource.UNRESOLVED
    assert plan.unresolved_inputs == (f"down GET {downstream_path}: {downstream_name}",)


@pytest.mark.parametrize(
    "downstream_path, downstream_name", [("/accounts/{id}", "id"), ("/accounts/{acctId}", "acctId")]
)
def test_same_resource_with_a_generic_or_abbreviated_id_binds(lexicon, downstream_path, downstream_name):
    plan = plan_binding(lexicon, "/accounts/{accountId}", "accountId", downstream_path, downstream_name)
    binding = plan.steps[0].bindings[0]
    assert (binding.source, binding.reference) == (BindingSource.UPSTREAM_REQUEST, "accountId")
    assert not plan.unresolved_inputs


@pytest.mark.parametrize("context, should_call", [({}, False), ({"path:id": "CUS-1"}, True)])
def test_unresolved_id_never_reuses_an_unrelated_upstream_id(lexicon, context, should_call):
    run = planned_run(lexicon, "/accounts/{id}", "id", "/customers/{id}/balances", "id")
    executor = PlanExecutor(run, MockDownstreams(run.downstreams, lexicon))
    result = asyncio.run(executor.execute("GET /accounts/{id}", {"id": "ACC-1", **context}))
    if should_call:
        assert len(result.calls) == 1
        assert "/customers/CUS-1/balances" in result.calls[0].url
        assert result.status == 200
    else:
        assert result.calls == []
        assert any("path:id" in warning for warning in result.warnings)
