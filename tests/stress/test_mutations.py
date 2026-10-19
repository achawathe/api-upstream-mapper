"""Accuracy when every downstream field is renamed the way real APIs differ.

Each seed restyles all eight sample downstreams and rewrites the answer key with the same
renames, so the matcher meets names it has never seen while ground truth stays exact.

lexicon mode: casing, abbreviations and synonyms the lexicon knows.
hard mode:    additionally dropped vowels, truncation, reversed word order and filler
              words that no lexicon lists (`blnc`, `entri`, `idAccount`, `amountValue`).
"""

import pytest

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import Outcome, grade
from api_mapper.pipeline.orchestrator import MappingPipeline
from tests.helpers import ERROR_CATALOG, UPSTREAM
from tests.stress.generators import write_mutated_answer_key, write_mutated_downstreams


def _grade(tmp_path, lexicon, seed, hard):
    downstreams, renamers = write_mutated_downstreams(tmp_path, seed, lexicon, hard=hard)
    key_path = write_mutated_answer_key(tmp_path, renamers)
    pipeline = MappingPipeline(lexicon)
    run = pipeline.run(pipeline.load(UPSTREAM, downstreams, ERROR_CATALOG)).run
    return grade(run.mappings, load_answer_key(key_path, run.upstream.name))


@pytest.mark.parametrize("seed", range(8))
def test_lexicon_renames(tmp_path, lexicon, seed):
    report = _grade(tmp_path, lexicon, seed, hard=False)
    assert report.counts[Outcome.WRONG_AUTO] == 0, report.failures()
    assert report.auto_precision >= 0.99, report.summary()
    assert report.recall >= 0.95, report.summary()


@pytest.mark.parametrize("seed", range(16))
def test_unseen_spellings(tmp_path, lexicon, seed):
    report = _grade(tmp_path, lexicon, seed, hard=True)
    assert report.counts[Outcome.WRONG_AUTO] <= 1, report.failures()
    assert report.auto_precision >= 0.98, report.summary()
    assert report.recall >= 0.70, report.summary()
