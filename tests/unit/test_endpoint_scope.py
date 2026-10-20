"""Mapping a chosen set of upstream endpoints gives the same decisions as mapping everything."""

import json
from dataclasses import replace

import pytest

from api_mapper.cli import main
from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import grade
from api_mapper.models import Override, OverrideAction
from api_mapper.pipeline.orchestrator import MappingPipeline
from tests.helpers import ANSWER_KEY, DOWNSTREAMS, ERROR_CATALOG, UPSTREAM

SELECTED = ("GET /accounts/{accountId}", "GET /accounts/{accountId}/transactions", "GET /accounts")


def decisions(run):
    return {
        m.target.key: (m.status, m.chosen.source.key if m.chosen else None, m.chosen and m.chosen.score, m.notes)
        for m in run.mappings
    }


@pytest.fixture(scope="module")
def runs(lexicon):
    pipeline = MappingPipeline(lexicon)
    inputs = pipeline.load(UPSTREAM, DOWNSTREAMS, ERROR_CATALOG)
    full = pipeline.run(inputs).run
    scoped = pipeline.run(replace(inputs, endpoints=SELECTED)).run
    return full, scoped


def test_scoped_run_maps_only_selected_endpoints_with_identical_decisions(runs):
    full, scoped = runs
    assert {m.target.endpoint for m in scoped.mappings} == set(SELECTED)
    expected = {key: value for key, value in decisions(full).items() if key.split("|")[1] in SELECTED}
    assert decisions(scoped) == expected
    assert scoped.scope == tuple(sorted(SELECTED))
    assert {plan.upstream_endpoint for plan in scoped.call_plans} == set(SELECTED)


def test_unknown_endpoints_are_reported_and_an_all_unknown_selection_maps_nothing(lexicon):
    pipeline = MappingPipeline(lexicon)
    inputs = pipeline.load(UPSTREAM, DOWNSTREAMS, ERROR_CATALOG)
    run = pipeline.run(replace(inputs, endpoints=("GET /nowhere",))).run
    assert run.mappings == []
    assert "selected endpoint GET /nowhere is not in the upstream spec" in run.warnings


def test_overrides_outside_the_selection_are_kept_but_not_applied(lexicon, runs):
    full, _ = runs
    outside = next(m for m in full.mappings if m.target.endpoint not in SELECTED)
    override = Override(outside.target.key, OverrideAction.REJECT)
    pipeline = MappingPipeline(lexicon)
    inputs = pipeline.load(UPSTREAM, DOWNSTREAMS, ERROR_CATALOG, (override,))
    result = pipeline.run(replace(inputs, endpoints=SELECTED))
    note = "1 saved decisions belong to endpoints outside the selection; kept, not applied"
    assert note in result.run.warnings
    assert not any("no longer exists upstream" in w for w in result.run.warnings)
    assert note in pipeline.reapply_overrides(result, (override,))


def test_grading_counts_only_selected_endpoints(runs):
    _, scoped = runs
    report = grade(scoped.mappings, load_answer_key(ANSWER_KEY, scoped.upstream.name))
    assert set(report.outcomes) == {m.target.key for m in scoped.mappings}


def test_cli_maps_only_the_endpoints_it_is_given(tmp_path):
    args = ["map", "--upstream", str(UPSTREAM), "--downstream", *map(str, DOWNSTREAMS), "--quiet"]
    assert main([*args, "--endpoint", "GET /accounts", "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "mapping-report.json").read_text())
    assert report["endpoints_mapped"] == ["GET /accounts"]
    assert {m["target"]["endpoint"] for m in report["mappings"]} == {"GET /accounts"}
