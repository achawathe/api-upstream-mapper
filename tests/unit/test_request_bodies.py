"""JSON request context survives loading, conservative planning and mock HTTP execution."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from api_mapper.loaders import build_api_spec
from api_mapper.loaders.request_body import body_parameters, json_body
from api_mapper.models import BindingSource, Endpoint, MappingStatus, Parameter
from api_mapper.normalize.inputs import bindable_body, compatible_body_input
from api_mapper.pipeline.orchestrator import MappingPipeline, PipelineInputs
from api_mapper.validation.executor import PlanExecutor
from api_mapper.validation.request_inputs import RequestInputError, request_parts

STRING = {"type": "string"}
BODY = {
    "type": "object", "required": ["access_token"],
    "properties": {
        "access_token": STRING,
        "client_id": STRING,
        "options": {"type": "object", "properties": {
            "account_ids": {"type": "array", "items": STRING},
        }},
    },
}


def _spec(name, path, operation):
    document = {"openapi": "3.0.3", "info": {"title": name, "version": "1"},
                "paths": {path: operation}}
    return build_api_spec(document, source="test", base_dir=Path("."), name=name)


def _response(properties):
    return {"200": {"description": "OK", "content": {"application/json": {
        "schema": {"type": "object", "required": list(properties), "properties": properties},
    }}}}


def _run(lexicon, body=BODY):
    upstream = _spec("up", "/accounts/{accountId}", {"get": {
        "parameters": [{"name": "accountId", "in": "path", "required": True, "schema": STRING}],
        "responses": _response({"accountId": STRING}),
    }})
    downstream = _spec("down", "/accounts/get", {"post": {
        "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
        "responses": _response({"accountId": STRING}),
    }})
    return MappingPipeline(lexicon).run(PipelineInputs(upstream, (downstream,))).run


def test_json_body_loader_retains_context(lexicon):
    run = _run(lexicon)
    endpoint = run.downstreams[0].endpoints[0]
    parameters = {p.name: p for p in endpoint.parameters}
    assert endpoint.request_schema == BODY and endpoint.request_required
    assert parameters["access_token"].required and parameters["access_token"].context_only
    assert parameters["client_id"].context_only
    assert not parameters["options.account_ids"].required
    assert bindable_body(parameters["options.account_ids"])
    mapping = run.mappings[0]
    assert mapping.chosen.source.endpoint == "POST /accounts/get"
    assert mapping.status is MappingStatus.REVIEW
    assert any("JSON body" in note for note in mapping.notes)
    bindings = {b.key: b for b in run.call_plans[0].steps[0].bindings}
    assert bindings["body:options.account_ids"].reference == "accountId"
    assert bindings["body:access_token"].source is BindingSource.UNRESOLVED
    assert any("access_token" in item for item in run.call_plans[0].unresolved_inputs)


def test_swagger_operation_body_overrides_shared_body():
    shared = [{"in": "body", "name": "old", "schema": BODY, "required": True}]
    chosen = {"type": "array", "items": STRING}
    assert json_body({"parameters": [{"in": "body", "schema": chosen}]}, shared) == (chosen, False)
    assert json_body({}, shared) == (BODY, True)
    assert json_body({"requestBody": {"content": {"application/vnd.test+json": {"schema": chosen}}}}, []) == (chosen, False)


@pytest.mark.parametrize("schema", [
    {"oneOf": [STRING, {"type": "integer"}]},
    {"type": "object", "properties": {"literal.dot": STRING}},
    {"type": "array", "items": {"type": "object", "properties": {"id": STRING}}},
])
def test_ambiguous_or_structured_body_remains_opaque(schema):
    parameters = body_parameters(schema, True)
    assert len(parameters) == 1 and parameters[0].name == "$body"
    assert not bindable_body(parameters[0])


def test_required_ancestry_and_activated_optional_objects():
    schema = {"type": "object", "properties": {"options": {
        "type": "object", "required": ["account_id", "region"],
        "properties": {"account_id": STRING, "region": STRING},
    }}}
    endpoint = Endpoint("POST", "/x", "x", parameters=body_parameters(schema, True),
                        request_schema=schema, request_required=True)
    assert all(not p.required for p in endpoint.parameters)
    assert request_parts(endpoint, {}).body == {}
    with pytest.raises(RequestInputError, match="body:options.region"):
        request_parts(endpoint, {"body:options.account_id": "a"})
    optional = {"type": "object", "required": ["token"], "properties": {"token": STRING}}
    endpoint = replace(endpoint, parameters=body_parameters(optional, False),
                       request_schema=optional, request_required=False)
    assert request_parts(endpoint, {}).body is None


def test_locations_and_scalar_array_binding_do_not_collide():
    endpoint = Endpoint("POST", "/accounts/{id}", "x", parameters=(
        Parameter("id", "path", True, STRING), Parameter("id", "query", True, STRING),
        Parameter("options.id", "body", True, {"type": "array", "items": STRING}),
    ))
    parts = request_parts(endpoint, {"path:id": "a/b", "query:id": "query", "body:options.id": "body"})
    assert parts.path == "/accounts/a%2Fb"
    assert parts.query == {"id": "query"}
    assert parts.body == {"options": {"id": ["body"]}}


@pytest.mark.parametrize(("source", "target", "expected"), [
    (STRING, {"type": "array", "items": STRING}, True),
    ({"type": "integer"}, STRING, False),
    ({"type": "string", "format": "date-time"}, {"type": "string", "format": "date"}, False),
    (STRING, {"type": "string", "enum": ["a"]}, False),
    ({"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a", "b"]}, True),
])
def test_body_bindings_require_compatible_shapes(source, target, expected):
    assert compatible_body_input(source, target) is expected


class StrictDownstream:
    def __init__(self):
        self.requests = []

    def base_url(self, api):
        return "https://mock.invalid"

    def transport(self):
        def respond(request):
            self.requests.append(request)
            assert request.method == "POST" and not request.url.query
            assert json.loads(request.content) == {"access_token": "test-token", "options": {"account_ids": ["ACC-2"]}}
            return httpx.Response(200, json={"accountId": "ACC-2"})
        return httpx.MockTransport(respond)


def test_executor_sends_filter_and_credentials_in_json_only(lexicon):
    run, downstream = _run(lexicon), StrictDownstream()
    result = asyncio.run(PlanExecutor(run, downstream).execute(
        "GET /accounts/{accountId}", {"accountId": "ACC-2", "body:access_token": "test-token"},
    ))
    assert len(downstream.requests) == 1 and result.body == {"accountId": "ACC-2"}
    assert "test-token" not in str(result.calls) + str(result.warnings)


def test_executor_does_not_send_request_without_required_context(lexicon):
    run, downstream = _run(lexicon), StrictDownstream()
    result = asyncio.run(PlanExecutor(run, downstream).execute("GET /accounts/{accountId}", {"accountId": "ACC-2"}))
    assert downstream.requests == [] and result.calls == []
    assert result.status == 422 and any("body:access_token" in warning for warning in result.warnings)


def test_body_reference_is_resolved_by_loader():
    document = {"openapi": "3.0.3", "info": {"title": "x", "version": "1"},
                "components": {"schemas": {"Request": BODY}},
                "paths": {"/x": {"post": {"requestBody": {"required": True, "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Request"}},
                }}, "responses": _response({"accountId": STRING})}}}}
    endpoint = build_api_spec(document, source="test", base_dir=Path("."), name="x").endpoints[0]
    assert {p.name for p in endpoint.parameters} == {"access_token", "client_id", "options.account_ids"}
    assert endpoint.request_schema["properties"] == BODY["properties"]


def test_planner_leaves_incompatible_body_binding_unresolved(lexicon):
    body = {"type": "object", "required": ["accountId"], "properties": {"accountId": {"type": "integer"}}}
    run = _run(lexicon, body)
    binding = run.call_plans[0].steps[0].bindings[0]
    assert binding.source is BindingSource.UNRESOLVED
    assert "body accountId" in run.call_plans[0].unresolved_inputs[0]


def test_body_credentials_do_not_establish_customer_scope(lexicon):
    from api_mapper.matching.reachability import Reachability
    from api_mapper.planning.call_planner import CallPlanner

    run = _run(lexicon, {"type": "object", "properties": {"client_id": STRING}})
    planner = CallPlanner(lexicon, run.upstream, run.downstreams, [])
    reach = Reachability(run.downstreams, [], planner.param_concepts, lexicon)
    customer = frozenset({planner.param_concepts("customerId", "/customers/{customerId}")})
    assert not reach.reachable(customer, ("down", "POST /accounts/get"))


def test_body_dependent_chains_inherit_review_but_not_missing_path_inputs(lexicon):
    from api_mapper.matching.reachability import Reachability
    from api_mapper.normalize.flattener import flatten_spec
    from api_mapper.normalize.profiler import Profiler
    from api_mapper.planning.call_planner import CallPlanner

    run = _run(lexicon)
    first = replace(run.downstreams[0].endpoints[0], response_schema={
        "type": "object", "properties": {"partyId": STRING},
    })
    second = Endpoint("GET", "/parties/{partyId}", "party", parameters=(Parameter("partyId", "path", True, STRING),))
    blocked = replace(first, path="/tenants/{tenantId}/accounts/get", parameters=(
        *first.parameters, Parameter("tenantId", "path", True, STRING),
    ))
    spec = replace(run.downstreams[0], endpoints=(first, second, blocked))
    sources = Profiler(lexicon).profile_spec(spec, flatten_spec(spec))
    planner = CallPlanner(lexicon, run.upstream, (spec,), sources)
    reach = Reachability((spec,), sources, planner.param_concepts, lexicon)
    account = frozenset({planner.param_concepts("accountId", "/accounts/{accountId}")})
    assert reach.reachable(account, ("down", second.key))
    assert reach.requires_body_review(("down", second.key), account)
    assert not reach.reachable(account, ("down", blocked.key))
    party = frozenset({planner.param_concepts("partyId", second.path)})
    assert not reach.requires_body_review(("down", second.key), party)


def test_location_is_exported_and_caller_context_preserves_json_types(lexicon):
    from api_mapper.api.app import ValidateBody
    from api_mapper.reporting.serialize import plan_to_dict

    plan = plan_to_dict(_run(lexicon).call_plans[0])
    assert all(binding["location"] == "body" for binding in plan["steps"][0]["bindings"])
    context = {"body:$body": {"ids": ["a", "b"]}}
    assert ValidateBody(endpoint="GET /x", params=context).params == context


def test_opaque_empty_array_is_preserved():
    schema = {"type": "array", "items": {"type": "object"}}
    endpoint = Endpoint("POST", "/x", "x", parameters=body_parameters(schema, True),
                        request_schema=schema, request_required=True)
    assert request_parts(endpoint, {"body:$body": []}).body == []


def test_upstream_credentials_cannot_supply_a_downstream_customer_id(lexicon):
    upstream = _spec("up", "/customers/get", {"post": {
        "requestBody": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"client_id": STRING},
        }}}}, "responses": _response({"customerId": STRING}),
    }})
    downstream = _spec("down", "/customers/{customerId}", {"get": {
        "parameters": [{"name": "customerId", "in": "path", "required": True, "schema": STRING}],
        "responses": _response({"customerId": STRING}),
    }})
    run = MappingPipeline(lexicon).run(PipelineInputs(upstream, (downstream,))).run
    binding = run.call_plans[0].steps[0].bindings[0]
    assert binding.source is BindingSource.UNRESOLVED
