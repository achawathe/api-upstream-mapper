"""Offline NLP retrieval, scoring safeguards and configuration contracts."""

import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from api_mapper.api.workspace import Workspace
from api_mapper.cli import main
from api_mapper.matching.assigner import Thresholds, assign
from api_mapper.matching.engine import MatchingEngine
from api_mapper.matching.semantic import (
    LocalNlpError,
    LocalSentenceEncoder,
    NlpSettings,
    SemanticIndex,
)
from api_mapper.models import FieldNode, MappingStatus
from api_mapper.normalize.profiler import Profiler


class Encoder:
    def __init__(self, vectors=None):
        self.calls = []
        self.vectors = vectors

    def encode(self, texts, **kwargs):
        self.calls.append(texts)
        return self.vectors if self.vectors is not None else [[1.0, 0.0] for _ in texts]


def profiles(lexicon, source_type="string"):
    profiler = Profiler(lexicon)
    target = profiler.profile(FieldNode(api="up", endpoint="GET /x", path="surname", type="string"), frozenset(), ())
    source = profiler.profile(
        FieldNode(api="down", endpoint="GET /x", path="patronymic", type=source_type), frozenset(), ()
    )
    return target, source


def test_nlp_discovers_pairs_excluded_by_lexical_gate(lexicon):
    target, source = profiles(lexicon)
    assert MatchingEngine(lexicon).prepare([target], [source]).score_all()[target.node.key] == []
    encoder = Encoder()
    prepared = MatchingEngine(lexicon, encoder=encoder).prepare([target], [source])
    candidates = prepared.score_all()[target.node.key]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert any(e.signal == "local_nlp" and e.score == 1 for e in candidate.evidence)
    assert any(e.signal == "anchor" for e in candidate.evidence)
    assert candidate == prepared.score_pair(target.node.key, source.node.key)
    assert len(encoder.calls) == 1
    assert (
        assign([target], {target.node.key: candidates}, Thresholds(auto=0, review=0))[0].status is MappingStatus.REVIEW
    )


def test_semantics_cannot_override_type_veto(lexicon):
    target, source = profiles(lexicon)
    target = replace(target, node=replace(target.node, format="date"), temporal=True)
    source = replace(source, node=replace(source.node, type="boolean"))
    prepared = MatchingEngine(lexicon, encoder=Encoder()).prepare([target], [source])
    candidate = prepared.score_all()[target.node.key][0]
    assert candidate.vetoed_by and candidate.score == 0
    assert (
        assign([target], {target.node.key: [candidate]}, Thresholds(auto=0, review=0))[0].status
        is MappingStatus.UNMAPPED
    )


def test_semantic_cutoff_and_stable_top_k(lexicon):
    target, source = profiles(lexicon)
    other = replace(source, node=replace(source.node, api="another"))
    index = SemanticIndex([target, source, other], Encoder(), NlpSettings(top_k=1))
    assert index.candidates_for(target, [source, other]) == [other]
    index = SemanticIndex([target, source], Encoder([[1, 0], [0, 1]]), NlpSettings())
    assert index.candidates_for(target, [source]) == []


@pytest.mark.parametrize("vectors", [[], [[0, 0], [1, 0]], [[float("nan"), 0], [1, 0]], [[1], [1, 0]]])
def test_invalid_embeddings_fail_clearly(lexicon, vectors):
    with pytest.raises(LocalNlpError):
        SemanticIndex(list(profiles(lexicon)), Encoder(vectors), NlpSettings())


def test_local_model_loading_forbids_downloads_and_remote_code(tmp_path, monkeypatch):
    calls = []

    def model(path, **kwargs):
        calls.append((path, kwargs))
        return Encoder()

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=model))
    LocalSentenceEncoder(str(tmp_path)).encode(["field description"])
    assert calls == [(str(tmp_path), {"device": "cpu", "local_files_only": True, "trust_remote_code": False})]
    with pytest.raises(LocalNlpError, match="folder does not exist"):
        LocalSentenceEncoder(str(tmp_path / "missing"))


def test_missing_optional_dependency_has_install_guidance(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(LocalNlpError, match="install local NLP dependencies"):
        LocalSentenceEncoder(str(tmp_path))


@pytest.mark.parametrize(
    "kwargs", [{"top_k": 0}, {"top_k": True}, {"min_similarity": 0}, {"min_similarity": float("nan")}]
)
def test_nlp_settings_validation(kwargs):
    with pytest.raises(ValueError):
        NlpSettings(**kwargs)


def test_workspace_persists_nlp_settings(tmp_path):
    workspace = Workspace(tmp_path)
    settings = NlpSettings(model_path="/local/model", top_k=4)
    workspace.configure(Thresholds(auto=0.8), settings)
    loaded = Workspace(tmp_path)
    assert loaded.nlp == settings
    assert loaded.thresholds.auto == 0.8
    assert loaded.state()["settings"]["nlp"]["model_path"] == "/local/model"


def test_cli_reports_missing_model_without_traceback(tmp_path, capsys):
    from tests.helpers import DOWNSTREAMS, UPSTREAM

    code = main(
        [
            "map",
            "--upstream",
            str(UPSTREAM),
            "--downstream",
            str(DOWNSTREAMS[0]),
            "--nlp-model",
            str(tmp_path / "missing"),
            "--quiet",
        ]
    )
    assert code == 2
    assert "local NLP model folder does not exist" in capsys.readouterr().err


def test_web_settings_and_nlp_run(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api_mapper.api import app as app_module
    from api_mapper.matching import engine
    from tests.conftest import SAMPLES

    workspace = Workspace(tmp_path)
    workspace.load_demo(SAMPLES)
    monkeypatch.setattr(app_module, "workspace", workspace)
    monkeypatch.setattr(engine, "LocalSentenceEncoder", lambda path: Encoder())
    with TestClient(app_module.app) as client:
        response = client.put(
            "/api/settings", json={"auto": 0.72, "review": 0.5, "nlp": {"model_path": "/local/model"}}
        )
        assert response.status_code == 200
        assert Workspace(tmp_path).nlp.model_path == "/local/model"
        # Older clients changing thresholds preserve the NLP configuration.
        assert client.put("/api/settings", json={"auto": 0.72, "review": 0.5}).status_code == 200
        assert workspace.nlp.model_path == "/local/model"
        assert (
            client.put("/api/settings", json={"auto": 0.72, "review": 0.5, "nlp": {"min_similarity": 2}}).status_code
            == 422
        )
        run_id = client.post("/api/runs").json()["run_id"]
        with client.stream("GET", f"/api/runs/{run_id}/events") as events:
            assert '"error": null' in events.read().decode()
        result = client.get("/api/report.json").json()
        assert any(
            e["signal"] == "local_nlp"
            for m in result["mappings"]
            for c in ([m["chosen"]] if m["chosen"] else [])
            for e in c["evidence"]
        )
        assert client.get("/api/report.xlsx").content.startswith(b"PK")


def test_web_missing_local_model_reports_failure(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api_mapper.api import app as app_module
    from tests.conftest import SAMPLES

    workspace = Workspace(tmp_path)
    workspace.load_demo(SAMPLES)
    workspace.configure(Thresholds(), NlpSettings(model_path=str(tmp_path / "missing")))
    monkeypatch.setattr(app_module, "workspace", workspace)
    with TestClient(app_module.app) as client:
        run_id = client.post("/api/runs").json()["run_id"]
        with client.stream("GET", f"/api/runs/{run_id}/events") as events:
            assert "local NLP model folder does not exist" in events.read().decode()
