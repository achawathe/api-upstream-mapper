"""Call inputs must identify the same resource, not merely share an identifier word."""

import pytest

from api_mapper.models import (
    ApiSpec,
    BindingSource,
    Candidate,
    Endpoint,
    FieldMapping,
    FieldNode,
    MappingStatus,
    Parameter,
    SpecKind,
)
from api_mapper.planning.call_planner import CallPlanner


def plan_binding(lexicon, upstream_path, upstream_name, downstream_path, downstream_name):
    upstream_endpoint = Endpoint(
        "GET", upstream_path, "up", parameters=(Parameter(upstream_name, "path", True, {"type": "string"}),)
    )
    downstream_endpoint = Endpoint(
        "GET", downstream_path, "down", parameters=(Parameter(downstream_name, "path", True, {"type": "string"}),)
    )
    upstream = ApiSpec("up", "up", "1", SpecKind.OPENAPI_3, "up", endpoints=(upstream_endpoint,))
    downstream = ApiSpec("down", "down", "1", SpecKind.OPENAPI_3, "down", endpoints=(downstream_endpoint,))
    mapping = FieldMapping(
        target=FieldNode("up", upstream_endpoint.key, "balance", "number"),
        status=MappingStatus.REVIEW,
        chosen=Candidate(FieldNode("down", downstream_endpoint.key, "balance", "number"), 0.8, ()),
    )
    return CallPlanner(lexicon, upstream, (downstream,), []).plan([mapping])[0]


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
