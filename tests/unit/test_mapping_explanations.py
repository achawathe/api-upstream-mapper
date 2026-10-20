"""Explanations expose uncertainty and remain tied to the source currently under review."""

from dataclasses import replace

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api_mapper.models import (
    Candidate,
    Evidence,
    EvidenceEffect,
    FieldMapping,
    FieldNode,
    MappingRun,
    MappingStatus,
)
from api_mapper.models.purpose import ContextClue
from api_mapper.reporting.comparison import explain_comparison
from api_mapper.reporting.excel_report import write_excel_report
from tests.unit.test_mapping_editor import setup_workspace


def test_attached_documentation_is_a_reference_not_proof_of_a_match():
    target = FieldNode(
        "channel", "GET /weather", "temperature", "number", description="Ambient air temperature in Celsius."
    )
    source = FieldNode(
        "provider",
        "GET /readings",
        "x7",
        "string",
        documentation=(ContextClue("Provider data definition.", "provider.md:2"),),
    )
    candidate = Candidate(
        source,
        0.81,
        (
            Evidence("documentation_context", 1, 0, "Provider data definition."),
            Evidence("local_nlp", 0.91, 0.2, "similar descriptions"),
            Evidence("body_context", 1, 0, "Confirm required request inputs."),
        ),
    )
    explanation = explain_comparison(FieldMapping(target, MappingStatus.REVIEW, candidate))
    assert not any("Provider data definition." in text for text in explanation["support"])
    assert any(r["location"] == "provider.md:2" for r in explanation["references"])
    assert any("does not prove" in text for text in explanation["concerns"])
    assert "Confirm required request inputs." in explanation["concerns"]
    assert any("similarity 0.91" in text for text in explanation["support"])
    assert any("no conversion step" in text for text in explanation["requirements"])
    assert "provider:x7" in explanation["summary"]


def test_alternative_comparison_exposes_the_decisive_signal_and_conflicts():
    target = FieldNode("up", "GET /records", "id", "string")
    chosen = Candidate(
        FieldNode("down", "GET /records", "stableKey", "string"),
        0.8,
        (Evidence("description", 0.95, 0.3, "same definition"),),
    )
    rival = Candidate(
        FieldNode("down", "GET /records", "requestId", "string"),
        0.55,
        (
            Evidence("description", 0.2, 0.3, "different event"),
            Evidence("role", 0.4, 0, "Request identity is not record identity", EvidenceEffect.MULTIPLIER),
        ),
    )
    explanation = explain_comparison(FieldMapping(target, MappingStatus.REVIEW, chosen, (rival,)))
    reason = explanation["alternatives"][0]["reason"]
    assert "stronger evidence for description" in reason
    assert "Request identity is not record identity" in reason
    assert "not probabilities" in reason


def test_draft_explanation_tracks_source_and_conversions_without_saving(tmp_path, monkeypatch):
    from api_mapper.api import app as module

    workspace = setup_workspace(tmp_path)
    monkeypatch.setattr(module, "workspace", workspace)
    mapping = workspace.result.run.mappings[0]
    original = mapping.chosen
    profile = next(iter(workspace.result.prepared.sources.values()))
    alternate = replace(
        profile, node=replace(profile.node, path="otherQuantity", description="A different provider field.")
    )
    workspace.result.prepared.sources[alternate.node.key] = alternate
    body = {
        "target_key": mapping.target.key,
        "source_key": alternate.node.key,
        "transforms": [{"kind": "cast", "params": {"to": "integer"}}],
    }
    with TestClient(module.app) as client:
        response = client.post("/api/mapping-explanation", json=body)
        assert response.status_code == 200
        explanation = response.json()
        assert "otherQuantity" in explanation["summary"]
        assert any("Convert to integer" in text for text in explanation["requirements"])
        assert any(r["text"] == "A different provider field." for r in explanation["references"])
        without = client.post("/api/mapping-explanation", json={**body, "transforms": []}).json()
        assert any("no conversion step" in text for text in without["requirements"])
        assert client.post("/api/mapping-explanation", json={**body, "source_key": "missing"}).status_code == 400
        assert (
            client.post("/api/mapping-explanation", json={**body, "transforms": [{"kind": "exec"}]}).status_code == 400
        )
    assert mapping.chosen is original
    assert workspace.overrides == []


def test_explanation_uncertainties_and_definitions_survive_exports(tmp_path):
    workspace = setup_workspace(tmp_path / "workspace")
    mapping = workspace.result.run.mappings[0]
    source = replace(mapping.chosen.source, description="Provider quantity, encoded as text.")
    mapping.chosen = replace(mapping.chosen, source=source)
    run = MappingRun(workspace.result.run.upstream, (), [mapping])
    workbook = load_workbook(write_excel_report(run, tmp_path / "report.xlsx"))
    rows = list(workbook["Candidate Comparison"].values)
    assert "Uncertainties" in rows[0]
    assert "Conversions and conditions" in rows[0]
    text = " ".join(str(cell) for row in rows for cell in row if cell is not None)
    assert "Provider quantity, encoded as text." in text
    assert "does not establish matching business definitions" in text
