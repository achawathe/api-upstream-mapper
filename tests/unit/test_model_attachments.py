"""Adding optional upstream models resolves references without replacing the API."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_mapper.api.workspace import FileRole, Workspace
from api_mapper.loaders import SpecLoadError, load_any
from api_mapper.normalize.flattener import flatten_spec

MODEL = b"Account:\n  type: object\n  properties:\n    ledgerKey: {type: string, description: Persistent bank account identifier}\n"


def upstream(workspace, reference="models.yaml#/Account"):
    document = {
        "openapi": "3.0.3",
        "info": {"title": "Accounts", "version": "1"},
        "paths": {
            "/accounts": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {"schema": {"$ref": reference}},
                            },
                        }
                    }
                }
            }
        },
    }
    return workspace.add_file(FileRole.UPSTREAM, "api.yaml", json.dumps(document).encode())


def test_models_clear_missing_reference_warnings_and_persist(tmp_path):
    workspace = Workspace(tmp_path)
    stored = upstream(workspace)
    old_path = stored.path
    assert stored.summary["warnings"]
    workspace.add_response_samples(stored.id, "GET /accounts", [("example.json", b'{"ledgerKey":"A"}')])
    attached = workspace.add_model_files(stored.id, [("models.yaml", MODEL)])
    assert attached.id == stored.id and attached.path != old_path
    assert attached.summary["warnings"] == []
    assert attached.model_files == ["models.yaml"]
    assert len(workspace.files) == 1
    restored = Workspace(tmp_path)
    assert restored.files[0].model_files == ["models.yaml"]
    assert restored.samples[0].file_id == stored.id
    nodes = flatten_spec(load_any(Path(attached.path)))
    assert nodes[0].path == "ledgerKey"
    assert nodes[0].description == "Persistent bank account identifier"
    assert Path(old_path).exists()


@pytest.mark.parametrize("reverse", [True, False])
def test_nested_model_dependencies_resolve_in_either_upload_order(tmp_path, reverse):
    workspace = Workspace(tmp_path)
    stored = upstream(workspace, "schemas/models.yaml#/Account")
    files = [("models.yaml", b'Account: {$ref: "types.yaml#/Account"}'), ("types.yaml", MODEL)]
    workspace.add_model_files(stored.id, files[::-1] if reverse else files)
    assert stored.summary["warnings"] == []
    assert stored.model_files == ["schemas/models.yaml", "schemas/types.yaml"]


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("models.yaml", b"Account: [unclosed"),
        ("models.yaml", b"123"),
        ("../models.yaml", MODEL),
        ("api.yaml", MODEL),
        ("models.txt", MODEL),
    ],
)
def test_invalid_attachment_preserves_original_bundle(tmp_path, filename, content):
    workspace = Workspace(tmp_path)
    stored = upstream(workspace)
    before = workspace.state()
    with pytest.raises((ValueError, SpecLoadError)):
        workspace.add_model_files(stored.id, [(filename, content)])
    assert workspace.state() == before


def test_missing_schema_pointer_still_has_a_warning(tmp_path):
    workspace = Workspace(tmp_path)
    stored = upstream(workspace, "models.yaml#/Missing")
    workspace.add_model_files(stored.id, [("models.yaml", MODEL)])
    assert any("pointer does not exist" in warning for warning in stored.summary["warnings"])


def test_repeated_model_names_require_the_referenced_paths(tmp_path):
    workspace = Workspace(tmp_path)
    stored = upstream(workspace, "left/models.yaml#/Account")
    document = json.loads(Path(stored.path).read_text())
    document["components"] = {
        "schemas": {"Left": {"$ref": "left/models.yaml#/Account"}, "Right": {"$ref": "right/models.yaml#/Account"}}
    }
    Path(stored.path).write_text(json.dumps(document))
    with pytest.raises(ValueError, match="more than one reference"):
        workspace.add_model_files(stored.id, [("models.yaml", MODEL)])
    workspace.add_model_files(stored.id, [("left/models.yaml", MODEL), ("right/models.yaml", MODEL)])
    assert stored.model_files == ["left/models.yaml", "right/models.yaml"]
    assert stored.summary["warnings"] == []


def test_models_route_updates_current_upstream_and_does_not_register_another_api(tmp_path, monkeypatch):
    from api_mapper.api import app as app_module

    workspace = Workspace(tmp_path)
    stored = upstream(workspace)
    monkeypatch.setattr(app_module, "workspace", workspace)
    with TestClient(app_module.app) as client:
        response = client.post(f"/api/files/{stored.id}/model-files", files=[("files", ("models.yaml", MODEL))])
        assert response.status_code == 200
        assert response.json()["file"]["summary"]["warnings"] == []
        assert len(client.get("/api/state").json()["files"]) == 1
        assert (
            client.post("/api/files/unknown/model-files", files=[("files", ("models.yaml", MODEL))]).status_code == 400
        )
    assert any(
        event["action"] == "Attach upstream model files" and event["outcome"] == "success"
        for event in workspace.activity.recent(100)
    )
