"""Action history survives restarts and failures without retaining response payloads."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from api_mapper.api.activity import ActivityLog
from api_mapper.api.workspace import RunState, Workspace


def test_history_is_thread_safe_rotates_and_recovers_partial_lines(tmp_path):
    log = ActivityLog(tmp_path, max_bytes=1500)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: log.record("Test action", sequence=i), range(60)))
    assert log.backup.exists()
    assert log.path.stat().st_size <= 1500 and log.backup.stat().st_size <= 1500
    before = log.recent()
    assert 1 < len(before) < 60
    with log.path.open("a") as stream:
        stream.write('{"incomplete":')
    assert ActivityLog(tmp_path).recent() == before
    assert len(log.recent(limit=3)) == 3
    log.record("Recovered action")
    assert log.recent()[0]["action"] == "Recovered action"


def test_request_errors_run_failures_and_reset_preserve_history(tmp_path, monkeypatch):
    from api_mapper.api import app as app_module

    workspace = Workspace(tmp_path)
    monkeypatch.setattr(app_module, "workspace", workspace)
    with TestClient(app_module.app) as client:
        response = client.put("/api/settings", json={"auto": 0.8, "review": 0.6})
        assert response.status_code == 200
        assert client.put("/api/settings", json={"auto": 0.1, "review": 0.9}).status_code == 400
        assert client.put("/api/settings", json={"auto": "PRIVATE-VALUE"}).status_code == 422
        assert client.post("/api/files", data={"role": "upstream"}, files=[("files", ("x.json", b'{"private":"PRIVATE-VALUE"}'))]).status_code == 400
        workspace._run(RunState("failed-run"))
        assert client.post("/api/reset").status_code == 200
        history = client.get("/api/activity").json()["events"]
        assert any(e["action"] == "Change settings" and e["outcome"] == "success" for e in history)
        assert any(e["action"] == "Upload files" and e["outcome"] == "failed" for e in history)
        assert any(e["details"].get("status") == 422 for e in history)
        assert any(e["action"] == "Mapping run" and e["outcome"] == "failed" for e in history)
        assert "PRIVATE-VALUE" not in (tmp_path / "activity.jsonl").read_text()
        assert Workspace(tmp_path).activity.recent() == history
        download = client.get("/api/activity?download=true&limit=1000")
        assert "attachment" in download.headers["content-disposition"]
        assert download.json()["events"] == history


def test_failed_log_write_does_not_undo_action(tmp_path, monkeypatch, caplog):
    log = ActivityLog(tmp_path)
    monkeypatch.setattr(type(tmp_path), "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("full")))
    log.record("Saved settings")
    assert "Could not save" in caplog.text
