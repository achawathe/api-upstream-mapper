"""Fifty downstream APIs: the eight sample APIs plus 42 generated ones.

The generated APIs share many generic field names with the real ones (id, status, amount,
accountId, nickname) but describe other things (branches, offers, disputes...). They must
not displace correct mappings, and the run must stay fast.
"""

import time

import pytest

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import Outcome, grade
from api_mapper.pipeline.orchestrator import MappingPipeline
from tests.helpers import ANSWER_KEY, DOWNSTREAMS, ERROR_CATALOG, UPSTREAM
from tests.stress.generators import write_noise_apis

NOISE_APIS = 42
TIME_BUDGET_SECONDS = 20


@pytest.fixture(scope="module")
def scaled(tmp_path_factory, lexicon):
    noise = write_noise_apis(tmp_path_factory.mktemp("noise"), NOISE_APIS, seed=7)
    pipeline = MappingPipeline(lexicon)
    inputs = pipeline.load(UPSTREAM, [*DOWNSTREAMS, *noise], ERROR_CATALOG)
    started = time.perf_counter()
    result = pipeline.run(inputs)
    return result, time.perf_counter() - started


def test_fifty_apis_load(scaled):
    result, _ = scaled
    assert len(result.run.downstreams) == len(DOWNSTREAMS) + NOISE_APIS


def test_fifty_apis_run_within_budget(scaled):
    _, seconds = scaled
    assert seconds < TIME_BUDGET_SECONDS, f"mapping 50 APIs took {seconds:.1f}s"


def test_noise_apis_never_win_automatically(scaled):
    result, _ = scaled
    noise_autos = [m for m in result.run.mappings if m.status.value == "auto" and m.chosen.source.api.startswith("noise")]
    assert noise_autos == [], [f"{m.target.key} <- {m.chosen.source.key}" for m in noise_autos]


def test_accuracy_holds_with_noise(scaled):
    result, _ = scaled
    report = grade(result.run.mappings, load_answer_key(ANSWER_KEY, result.run.upstream.name))
    assert report.counts[Outcome.WRONG_AUTO] == 0, report.failures()
    assert report.auto_precision >= 0.98, report.summary()
    assert report.recall >= 0.95, report.summary()
