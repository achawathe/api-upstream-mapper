"""End-to-end accuracy on FDX (Core Exchange 6.4) against the Northwind downstream APIs.

The bar: no wrong automatic mapping, at least 98% precision on everything decided
automatically, and every expected mapping surfaced (automatically or for review).
"""

import json

import pytest

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import Outcome, grade
from api_mapper.reporting.serialize import run_to_dict
from tests.helpers import ANSWER_KEY, run_sample


@pytest.fixture(scope="module")
def result(lexicon):
    return run_sample(lexicon)


@pytest.fixture(scope="module")
def report(result):
    return grade(result.run.mappings, load_answer_key(ANSWER_KEY, result.run.upstream.name))


def test_no_wrong_automatic_mappings(report):
    assert report.counts[Outcome.WRONG_AUTO] == 0, report.failures()


def test_automatic_precision(report):
    assert report.auto_precision >= 0.98, report.summary()


def test_every_expected_mapping_is_surfaced(report):
    assert report.counts[Outcome.MISSED] == 0, report.failures()
    assert report.recall >= 0.97, report.summary()


def test_most_expected_mappings_need_no_review(report):
    assert report.auto_recall >= 0.85, report.summary()


def test_decoy_api_never_maps_automatically(result):
    decoys = [
        m for m in result.run.mappings if m.chosen and m.chosen.source.api == "transfers" and m.status.value == "auto"
    ]
    assert decoys == []


def test_runs_are_deterministic(lexicon, result):
    again = run_sample(lexicon)
    first = json.dumps(run_to_dict(result.run, include_timings=False), sort_keys=True, default=str)
    second = json.dumps(run_to_dict(again.run, include_timings=False), sort_keys=True, default=str)
    assert first == second
