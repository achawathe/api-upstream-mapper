"""The HTTP API the GUI uses, driven end to end against a throwaway workspace."""

import importlib
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    os.environ["API_MAPPER_WORKSPACE"] = str(tmp_path_factory.mktemp("workspace"))
    from api_mapper.api import app as app_module

    importlib.reload(app_module)
    with TestClient(app_module.app) as test_client:
        yield test_client


def _run(client) -> dict:
    run_id = client.post("/api/runs").json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        events = [line for line in stream.iter_lines() if line.startswith("data:")]
    assert events, "the run streamed no progress events"
    deadline = time.time() + 30
    while time.time() < deadline:
        response = client.get("/api/result")
        if response.status_code == 200:
            return response.json()
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_run_without_inputs_reports_a_clear_error(client):
    run_id = client.post("/api/runs").json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        body = "\n".join(stream.iter_lines())
    assert "add an upstream spec first" in body


def test_demo_run_override_validate_and_download(client):
    state = client.post("/api/demo").json()
    assert len([f for f in state["files"] if f["role"] == "downstream"]) == 8

    result = _run(client)
    assert result["accuracy"]["auto_precision"] == 1.0
    assert result["summary"]["auto"] > 150

    target = next(m for m in result["mappings"] if m["target"]["path"] == "paymentNetworks[].bankId")
    rejected = client.post(
        "/api/overrides", json={"target_key": target["target"]["key"], "action": "reject", "note": "not yet"}
    ).json()
    assert rejected["mapping"]["status"] == "rejected"
    restored = client.delete("/api/overrides", params={"target_key": target["target"]["key"]}).json()
    assert restored["mapping"]["status"] == target["status"]

    validation = client.post("/api/validate", json={"endpoint": "GET /accounts", "params": {}}).json()
    assert validation["status"] == 200 and validation["calls"]

    excel = client.get("/api/report.xlsx")
    assert excel.status_code == 200 and excel.content[:2] == b"PK"
    history = client.get("/api/activity?limit=1000").json()["events"]
    assert any(e["action"] == "Mapping run" and e["outcome"] == "success" for e in history)
    assert any(e["action"] == "Change mapping decision" and e["details"]["decision"] == "reject" for e in history)
    assert any(e["details"].get("route") == "/api/validate" and e["outcome"] == "success" for e in history)


def test_sample_endpoint_upload_infers_an_api(client):
    payload = b'{"txnRef": "A1", "amt": 12.5, "status": "OK"}'
    response = client.post(
        "/api/sample-endpoints",
        data={"api_name": "fx", "method": "GET", "path": "/fx/{ref}"},
        files=[("files", ("one.json", payload, "application/json"))],
    )
    summary = response.json()["file"]["summary"]
    assert summary["ok"] and summary["kind"] == "sample-payloads" and summary["endpoints"] == 1


def test_broken_upload_is_reported_not_fatal(client):
    response = client.post(
        "/api/files", data={"role": "downstream"}, files=[("files", ("bad.yaml", b"paths: [unclosed", "text/yaml"))]
    )
    stored = response.json()["files"][0]
    assert stored["summary"]["ok"] is False


def test_endpoint_selection_limits_the_run_and_persists(client):
    client.post("/api/demo")
    listed = client.get("/api/upstream/endpoints").json()["endpoints"]
    assert listed and all(item["fields"] > 0 and not item["selected"] for item in listed)
    chosen = [item["key"] for item in listed[:2]]

    state = client.put("/api/endpoint-scope", json={"endpoints": chosen}).json()
    assert state["settings"]["endpoints"] == chosen
    assert client.put("/api/endpoint-scope", json={"endpoints": ["GET /nowhere"]}).status_code == 400

    result = _run(client)
    assert {m["target"]["endpoint"] for m in result["mappings"]} == set(chosen)
    assert result["endpoints_mapped"] == sorted(chosen)
    validation_options = client.get("/api/validate/options")
    assert validation_options.status_code == 200
    assert {item["endpoint"] for item in validation_options.json()["endpoints"]} == set(chosen)
    assert [item["key"] for item in client.get("/api/upstream/endpoints").json()["endpoints"] if item["selected"]] == [
        key for key in (item["key"] for item in listed) if key in chosen
    ]

    client.put("/api/endpoint-scope", json={"endpoints": []})
    assert {m["target"]["endpoint"] for m in _run(client)["mappings"]} > set(chosen)


def test_unresolved_context_ids_are_distinct_from_upstream_request_ids(client, lexicon, monkeypatch):
    from api_mapper.api import app as app_module
    from tests.unit.test_call_planner import planned_run

    run = planned_run(lexicon, "/accounts/{id}", "id", "/customers/{id}/balances", "id")
    monkeypatch.setattr(app_module.workspace, "result", SimpleNamespace(run=run))
    options = client.get("/api/validate/options").json()["endpoints"][0]
    assert options["path_params"] == ["id"]
    assert options["context_params"] == ["path:id"]
