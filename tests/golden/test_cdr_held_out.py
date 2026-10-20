"""Accuracy on the Australian Consumer Data Right banking APIs, which no rule was written for.

The answer key was written from the specs before the first run. The general defects it
exposed were fixed (tags no longer set an API-wide account family; single-record fields must
come from an endpoint about the same record; a category defined as an MCC prefers a merchant
category code), so this set is no longer untouched; see samples/held-out/cdr/README.md.
"""

import pytest

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import Outcome, grade
from api_mapper.pipeline.orchestrator import MappingPipeline
from tests.conftest import SAMPLES
from tests.helpers import UPSTREAM

CDR = SAMPLES / "held-out" / "cdr"


@pytest.fixture(scope="module")
def report(lexicon):
    pipeline = MappingPipeline(lexicon)
    run = pipeline.run(pipeline.load(UPSTREAM, [CDR / "cds_banking.json", CDR / "cds_common.json"])).run
    return grade(run.mappings, load_answer_key(CDR / "answer_key.yaml", run.upstream.name))


def test_no_wrong_automatic_mapping(report):
    assert report.counts[Outcome.WRONG_AUTO] + report.counts[Outcome.SPURIOUS_AUTO] == 0, report.failures()


def test_precision_and_recall(report):
    assert report.auto_precision >= 0.95, report.summary()
    assert report.recall >= 0.90, report.summary()
