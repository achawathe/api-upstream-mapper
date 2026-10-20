"""Accuracy on the Australian Consumer Data Right banking APIs, which no rule was written for.

The answer key was written from the specs before the first run. The general defects it
exposed were fixed (tags no longer set an API-wide account family; single-record fields must
come from an endpoint about the same record; a category defined as an MCC prefers a merchant
category code), so this set is no longer untouched; see samples/held-out/cdr/README.md.
"""

import json

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


def _undocumented(node):
    if isinstance(node, dict):
        return {
            k: _undocumented(v) for k, v in node.items() if not (k in ("description", "summary") and isinstance(v, str))
        }
    if isinstance(node, list):
        return [_undocumented(v) for v in node]
    return node


def test_no_wrong_automatic_mapping_without_descriptions(lexicon, tmp_path):
    """Poorly documented APIs: the same specs with every description and summary removed."""
    downstreams = []
    for name in ("cds_banking.json", "cds_common.json"):
        stripped = tmp_path / name
        stripped.write_text(json.dumps(_undocumented(json.loads((CDR / name).read_text()))))
        downstreams.append(stripped)
    pipeline = MappingPipeline(lexicon)
    run = pipeline.run(pipeline.load(UPSTREAM, downstreams)).run
    report = grade(run.mappings, load_answer_key(CDR / "answer_key.yaml", run.upstream.name))
    assert report.counts[Outcome.WRONG_AUTO] + report.counts[Outcome.SPURIOUS_AUTO] == 0, report.failures()
    assert report.recall >= 0.90, report.summary()
