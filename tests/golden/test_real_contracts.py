"""Pinned public contracts: exact origins, known ambiguity guards, and example-value projections."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from api_mapper.evaluation.contracts import grade_contract
from api_mapper.models import MappingStatus
from api_mapper.pipeline.orchestrator import MappingPipeline
from api_mapper.transforms.apply import apply_transforms
from api_mapper.validation.assembler import extract, write
from api_mapper.validation.checks import check_document

FIXTURES = Path(__file__).resolve().parents[2] / "samples" / "real-contracts"
UPSTREAM = FIXTURES.parent / "upstream" / "fdx" / "core-exchange-6.4.yaml"
LABELS = json.loads((FIXTURES / "answer-key.json").read_text())


@pytest.fixture(scope="module")
def public_runs(lexicon):
    pipeline = MappingPipeline(lexicon)
    return {
        provider: pipeline.run(pipeline.load(UPSTREAM, [FIXTURES / provider / "openapi.json"]))
        for provider in ("uk", "plaid")
    }


def test_pinned_fixture_checksums():
    for source in json.loads((FIXTURES / "provenance.json").read_text()):
        assert hashlib.sha256((FIXTURES / source["fixture"]).read_bytes()).hexdigest() == source["fixture_sha256"]


@pytest.mark.parametrize("provider", ["uk", "plaid"])
def test_public_contract_origins_and_safety_budget(public_runs, provider):
    result = public_runs[provider]
    labels = [row for row in LABELS if row["provider"] == provider]
    grade = grade_contract(result.run.mappings, labels, set(result.prepared.sources))
    assert grade.summary["wrong_automatic"] == 0
    assert grade.summary["correct"] >= {"uk": 16, "plaid": 15}[provider]
    assert grade.summary["labels"] == {"uk": 50, "plaid": 49}[provider]


@pytest.mark.parametrize("provider", ["uk", "plaid"])
def test_missing_or_duplicate_contract_labels_fail(public_runs, provider):
    result = public_runs[provider]
    label = next(row for row in LABELS if row["provider"] == provider and row["expected"])
    with pytest.raises(ValueError, match="duplicate"):
        grade_contract(result.run.mappings, [label, label], set(result.prepared.sources))
    with pytest.raises(ValueError, match="sources missing"):
        grade_contract(result.run.mappings, [label], set())


def test_uk_booking_date_is_not_value_date(public_runs):
    result = public_runs["uk"]
    target = "GET /accounts/{accountId}/transactions|<DepositTransaction>transactions[].postedTimestamp"
    mapping = next(m for m in result.run.mappings if m.target.key.split("|", 1)[1] == target)
    assert mapping.chosen.source.path == "Data.Transaction[].BookingDateTime"
    assert mapping.status in {MappingStatus.AUTO, MappingStatus.REVIEW}


def test_plaid_published_examples_preserve_each_account_identity(public_runs):
    result = public_runs["plaid"]
    mappings = [
        m
        for m in result.run.mappings
        if m.target.endpoint == "GET /accounts"
        and m.target.variant == "DepositAccountDescriptor"
        and m.target.path in {"accounts[].accountId", "accounts[].accountNumberDisplay"}
    ]
    endpoints = {e.key: e for e in result.run.downstreams[0].endpoints}
    for mapping in mappings:
        assert mapping.chosen is not None
        source = mapping.chosen.source
        payload = endpoints[source.endpoint].response_examples[0]
        original = extract(payload, source.path)
        values = [apply_transforms(mapping.chosen.transforms, value) for value in original]
        projected = {}
        write(projected, mapping.target.path, values)
        assert len(projected["accounts"]) == len(payload["accounts"])
        assert extract(projected, mapping.target.path) == original
        assert check_document(projected, [replace(mapping.target, required=True)]) == []
