"""Model-file bundles and documentation examples reach the same schema-based matcher."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_mapper.api.workspace import FileRole, RunState, Workspace
from api_mapper.loaders import load_any
from api_mapper.loaders.response_samples import attach_responses
from api_mapper.matching.engine import MatchingEngine
from api_mapper.models import ApiSpec, Endpoint, FieldNode, SpecKind
from api_mapper.normalize.flattener import flatten_spec
from api_mapper.normalize.profiler import Profiler
from api_mapper.normalize.sample_context import describe_samples
from tests.unit.test_semantic import Encoder

SCHEMA = {"type": "object", "required": ["accountId"], "properties": {
    "accountId": {"type": "string", "description": "Unique account identifier"},
    "status": {"type": "string", "description": "Account status", "enum": ["OPEN", "CLOSED"]},
    "balance": {"type": "number", "description": "Available account balance"},
}}


def _spec(schema=SCHEMA):
    return {"openapi": "3.0.3", "info": {"title": "Accounts", "version": "1"},
            "paths": {"/accounts": {"get": {"responses": {"200": {"description": "OK", "content": {
                "application/json": {"schema": schema},
            }}}}}}}


def _swagger(schema=SCHEMA):
    return {"swagger": "2.0", "info": {"title": "Accounts", "version": "1"},
            "paths": {"/accounts": {"get": {"responses": {"200": {"description": "OK", "schema": schema}}}}}}


def _upload(workspace, role, name="api.json", schema=SCHEMA):
    return workspace.add_file(role, name, json.dumps(_spec(schema)).encode())


def _run(workspace):
    state = RunState("test")
    workspace._run(state)
    assert state.error is None, state.error
    return workspace.result


@pytest.mark.parametrize(("factory", "models_key"), [(_spec, "components"), (_swagger, "definitions")])
def test_downstream_api_with_embedded_models_is_registered_once(tmp_path, factory, models_key):
    workspace = Workspace(tmp_path)
    document = factory()
    document[models_key] = {"schemas": {"Account": SCHEMA}} if models_key == "components" else {"Account": SCHEMA}
    stored = workspace.add_files(FileRole.DOWNSTREAM, [
        ("api.json", json.dumps(document).encode()),
        ("standalone.json", json.dumps(SCHEMA).encode()),
    ])
    assert [s.name for s in stored] == ["api.json", "standalone.json"]
    assert len(workspace.files) == 2


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("role", [FileRole.UPSTREAM, FileRole.DOWNSTREAM])
@pytest.mark.parametrize("document", [_spec, _swagger])
def test_models_yaml_is_a_companion_regardless_of_upload_order(tmp_path, reverse, role, document):
    workspace = Workspace(tmp_path)
    uploads = [("bundle/models/account.yaml", b"Account:\n  type: object\n  properties:\n    id: {type: string, description: Account identity}\n"),
               ("bundle/api.json", json.dumps(document({"$ref": "models/account.yaml#/Account"})).encode())]
    stored = workspace.add_files(role, uploads[::-1] if reverse else uploads)
    assert len(stored) == 1 and stored[0].name == "bundle/api.json"
    assert stored[0].summary["warnings"] == []
    nodes = flatten_spec(load_any(Path(stored[0].path)))
    assert [n.path for n in nodes] == ["id"]
    assert nodes[0].description == "Account identity"
    spec = attach_responses(load_any(Path(stored[0].path)), "GET /accounts", [("docs.json", {"id": "EXAMPLE-1"})])
    assert flatten_spec(spec)[0].sample_sources == ("docs.json",)


def test_removing_one_downstream_keeps_shared_model_files(tmp_path):
    workspace = Workspace(tmp_path)
    files = workspace.add_files(FileRole.DOWNSTREAM, [
        ("api.json", json.dumps(_spec({"$ref": "models/shared%20model.yaml#/Account"})).encode()),
        ("nested/other.json", json.dumps(_swagger({"$ref": "../models/shared%20model.yaml#/Account"})).encode()),
        ("models/shared model.yaml", b"Account:\n  type: object\n  properties:\n    id: {type: string}\n"),
    ])
    workspace.remove_file(files[0].id)
    assert flatten_spec(load_any(Path(files[1].path)))[0].path == "id"
    workspace.remove_file(files[1].id)
    assert list((tmp_path / "files").iterdir()) == []


def test_failed_bundle_preserves_existing_upstream(tmp_path):
    workspace = Workspace(tmp_path)
    original = _upload(workspace, FileRole.UPSTREAM)
    with pytest.raises(ValueError, match="one upstream entrypoint"):
        workspace.add_files(FileRole.UPSTREAM, [("a.json", json.dumps(_spec()).encode()), ("b.json", json.dumps(_spec()).encode())])
    assert workspace.files == [original] and Path(original.path).exists()


@pytest.mark.parametrize("names", [["../escape.yaml"], ["/absolute.yaml"], ["same.json", "same.json"], ["C:\\escape.yaml"]])
def test_bundle_rejects_unsafe_or_colliding_paths(tmp_path, names):
    workspace = Workspace(tmp_path)
    with pytest.raises(ValueError):
        workspace.add_files(FileRole.UPSTREAM, [(name, b"{}") for name in names])
    assert workspace.files == []


def test_documentation_examples_supplement_specs_and_survive_reload(tmp_path):
    workspace = Workspace(tmp_path)
    upstream = _upload(workspace, FileRole.UPSTREAM)
    downstream_schema = {**SCHEMA, "properties": {**SCHEMA["properties"], "status": {"type": "string", "description": "Account status"}}}
    downstream = _upload(workspace, FileRole.DOWNSTREAM, "down.json", downstream_schema)
    original = Path(downstream.path).read_bytes()
    workspace.add_response_samples(upstream.id, "GET /accounts", [("up-doc.json", b'{"status":"OPEN"}')])
    attachment = workspace.add_response_samples(downstream.id, "GET /accounts", [
        ("response.json", b'{"accountId":"ACC-1","status":"OPEN","balance":12.5}'),
        ("another.json", b'{"accountId":"ACC-2","status":"CLOSED","balance":8}'),
    ])
    workspace = Workspace(tmp_path)
    result = _run(workspace)
    assert len(result.run.downstreams) == 1
    assert Path(downstream.path).read_bytes() == original
    endpoint = result.run.downstreams[0].endpoints[0]
    assert endpoint.response_schema == downstream_schema
    nodes = {n.path: n for n in flatten_spec(result.run.downstreams[0])}
    assert nodes["status"].enum == () and nodes["status"].observed == ("OPEN", "CLOSED")
    assert nodes["status"].sample_sources == ("response.json", "another.json")
    assert "label OPEN" in nodes["status"].sample_context
    assert nodes["balance"].type == "number" and not nodes["balance"].required
    mapping = next(m for m in result.run.mappings if m.target.path == "status")
    assert mapping.chosen.source.path == "status"
    assert any(t.params.get("from_samples") for t in mapping.chosen.transforms)
    workspace.remove_response_samples(attachment.id)
    assert len(workspace.samples) == 1 and workspace.result is None
    workspace.remove_file(upstream.id)
    assert workspace.samples == []


def test_endpoint_attachment_is_explicit_and_bad_json_does_not_persist(tmp_path):
    workspace = Workspace(tmp_path)
    file = _upload(workspace, FileRole.UPSTREAM)
    with pytest.raises(KeyError):
        workspace.add_response_samples(file.id, "GET /missing", [("x.json", b"{}")])
    for payload in (b'{"x": NaN}', b"not json", b'"string response"'):
        with pytest.raises(ValueError):
            workspace.add_response_samples(file.id, "GET /accounts", [("x.json", payload)])
    assert workspace.samples == []


def test_examples_do_not_add_undeclared_fields_or_change_declared_enums(tmp_path):
    workspace = Workspace(tmp_path)
    file = _upload(workspace, FileRole.UPSTREAM)
    spec = attach_responses(load_any(Path(file.path)), "GET /accounts", [("docs.json", {"extra": "new", "status": "UNKNOWN"})])
    nodes = {n.path: n for n in flatten_spec(spec)}
    assert "extra" not in nodes
    assert nodes["status"].enum == ("OPEN", "CLOSED")
    assert nodes["status"].observed == ("UNKNOWN",)


def test_documentation_samples_follow_root_discriminators_and_skip_unknown_branch():
    schema = {"discriminator": {"propertyName": "kind"}, "oneOf": [
        {"title": kind, "type": "object", "properties": {"kind": {"enum": [kind]}, "name": {"type": "string"}}}
        for kind in ("LOAN", "CARD")
    ]}
    endpoint = Endpoint("GET", "/x", "x", response_schema=schema)
    spec = ApiSpec("api", "API", "1", SpecKind.OPENAPI_3, "test", endpoints=(endpoint,))
    spec = attach_responses(spec, endpoint.key, [("card.json", {"kind": "CARD", "name": "Visa"}),
                                               ("unknown.json", {"name": "Ambiguous"})])
    nodes = {(n.variant, n.path): n for n in flatten_spec(spec)}
    assert nodes["CARD", "name"].observed == ("Visa",)
    assert nodes["LOAN", "name"].observed == ()


def test_local_nlp_receives_bounded_documentation_context(lexicon):
    profiler = Profiler(lexicon)
    node = FieldNode("up", "GET /x", "state", "string", description="Account state",
                     sample_context=describe_samples(["OPEN", "CLOSED"]), sample_sources=("doc.json",))
    target = profiler.profile(node, frozenset(), ())
    source = profiler.profile(replace(node, api="down"), frozenset(), ())
    encoder = Encoder()
    prepared = MatchingEngine(lexicon, encoder=encoder).prepare([target], [source])
    assert "Documentation response examples: label OPEN; label CLOSED." in encoder.calls[0][0]
    assert prepared.score_pair(target.node.key, source.node.key) is not None
    context = describe_samples(["ACC-123456", "person@example.org", "2026-10-19", "2026-10-19T12:30:00Z"])
    assert "ACC-123456" not in context and "person@example.org" not in context
    assert "ISO calendar dates" in context and "ISO timestamps" in context


def test_http_upload_attach_run_and_remove(tmp_path, monkeypatch):
    from api_mapper.api import app as app_module

    monkeypatch.setattr(app_module, "workspace", Workspace(tmp_path))
    with TestClient(app_module.app) as client:
        files = [("files", ("models.yaml", b"Account:\n  type: object\n  properties:\n    status: {type: string}\n", "text/yaml")),
                 ("files", ("api.json", json.dumps(_spec({"$ref": "models.yaml#/Account"})).encode(), "application/json"))]
        response = client.post("/api/files", data={"role": "upstream"}, files=files)
        assert response.status_code == 200
        upstream = response.json()["files"][0]
        assert upstream["name"] == "api.json"
        endpoints = client.get(f'/api/files/{upstream["id"]}/endpoints').json()["endpoints"]
        assert endpoints == ["GET /accounts"]
        url = f'/api/files/{upstream["id"]}/response-samples'
        attached = client.post(url, data={"endpoint": endpoints[0]}, files=[("files", ("docs.json", b'{"status":"OPEN"}', "application/json"))])
        assert attached.status_code == 200
        assert len(client.get("/api/state").json()["response_samples"]) == 1
        assert client.post(url, data={"endpoint": "GET /missing"}, files=[("files", ("x.json", b"{}"))]).status_code == 400
        sample_id = attached.json()["samples"]["id"]
        assert client.delete(f"/api/response-samples/{sample_id}").json()["response_samples"] == []
