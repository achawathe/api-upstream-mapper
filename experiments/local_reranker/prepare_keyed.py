"""Build app-shaped candidate packets from a labelled downstream set, for training or a fresh test.

Packets come from the application's own retrieval and scoring, the same way prepare_public
builds the public set, so the model sees real field text and twelve-candidate lists. Labels
come from an answer key. Training rows are shuffled with random candidate IDs, required
targets whose source was not retrieved are skipped, and abstentions are cut to the number of
positives so NONE is not the easy answer. Test rows keep every acceptable answer.

    PYTHONPATH=.:src python -m experiments.local_reranker.prepare_keyed --output DIR
"""

import argparse
import json
import random
import tempfile
from pathlib import Path

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.matching.semantic import NlpSettings
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline
from experiments.local_reranker.augment import _rebuild
from experiments.local_reranker.prepare_public import field
from experiments.local_reranker.runtime import offline, read_rows, write_json
from tests.stress.generators import write_mutated_answer_key, write_mutated_downstreams

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
UPSTREAM = SAMPLES / "upstream/fdx/core-exchange-6.4.yaml"
ERRORS = SAMPLES / "upstream/fdx/error-catalog.yaml"
NORTHWIND = [
    SAMPLES / "downstream" / path
    for path in (
        "core-accounts/openapi.yaml",
        "deposits/swagger.json",
        "cards/openapi.json",
        "loans/openapi.yaml",
        "parties/openapi.yaml",
        "ledger/openapi.json",
        "routing/manifest.yaml",
        "transfers/openapi.yaml",
    )
]
CDR = SAMPLES / "held-out/cdr"
TRAIN_VARIANTS = (None, (0, False), (1, False), (0, True), (1, True))
VALID_VARIANT = (9, True)
TEST_NONE = 40


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    offline()
    lexicon = Lexicon.load()
    system = read_rows(ROOT / "experiments/local_reranker/data/valid.jsonl")[0]["messages"][0]
    rng = random.Random(args.seed)
    train = [row for variant in TRAIN_VARIANTS for row in _training(_northwind(lexicon, variant), system, rng)]
    rng.shuffle(train)
    seen = {_identity(row) for row in train}
    valid = [row for row in _training(_northwind(lexicon, VALID_VARIANT), system, rng) if _identity(row) not in seen]
    cdr = _cases(lexicon, [CDR / "cds_banking.json", CDR / "cds_common.json"], CDR / "answer_key.yaml", None)
    test = _test(cdr, system, rng)
    for name, rows in (("train", train), ("valid", valid), ("cdr-test", test)):
        (args.output / f"{name}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (args.output / "test.jsonl").write_bytes((ROOT / "experiments/local_reranker/data/test.jsonl").read_bytes())
    write_json(
        args.output / "metadata.json",
        {
            "train": {"variants": [str(v) for v in TRAIN_VARIANTS], "rows": len(train)},
            "valid": {"variant": str(VALID_VARIANT), "rows": len(valid)},
            "cdr-test": {"rows": len(test), "none_sampled": TEST_NONE},
            "test.jsonl": "copied unchanged from data/ so the data audit can run",
        },
    )
    print("KEYED_PACKETS_WRITTEN", len(train), len(valid), len(test), flush=True)


def _northwind(lexicon, variant):
    if variant is None:
        return _cases(lexicon, NORTHWIND, SAMPLES / "answer_key.yaml", ERRORS)
    seed, hard = variant
    with tempfile.TemporaryDirectory() as folder:
        downstreams, renamers = write_mutated_downstreams(Path(folder), seed, lexicon, hard=hard)
        return _cases(lexicon, downstreams, write_mutated_answer_key(Path(folder), renamers), ERRORS)


def _cases(lexicon, downstreams, key_path, errors) -> list[tuple[dict, list[str]]]:
    pipeline = MappingPipeline(lexicon, nlp=NlpSettings(model_path=str(ROOT / "models/all-MiniLM-L6-v2")))
    result = pipeline.run(pipeline.load(UPSTREAM, downstreams, errors))
    key = load_answer_key(key_path, result.run.upstream.name)
    cases = []
    for mapping in result.run.mappings:
        expectation = key.for_target(mapping.target.key)
        if expectation is not None and expectation.derived:
            continue
        target = result.prepared.targets[mapping.target.key]
        candidates = [
            candidate
            for source in result.prepared.index.candidates_for(target)
            if (candidate := result.prepared.scorer.score(target, source)) is not None
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda candidate: (candidate.vetoed_by is not None, -candidate.score, candidate.source.key))
        candidates = candidates[:12]
        if mapping.chosen and all(candidate.source.key != mapping.chosen.source.key for candidate in candidates):
            candidates[-1:] = [mapping.chosen]
        candidates.sort(key=lambda candidate: candidate.source.key)
        options = [
            {
                "candidate_id": f"C{i + 1}",
                "source_key": candidate.source.key,
                **field(candidate.source),
                "prohibited": bool(candidate.vetoed_by),
                "constraint": candidate.vetoed_by,
            }
            for i, candidate in enumerate(candidates)
        ]
        sources = expectation.sources if expectation else frozenset()
        expected = [o["candidate_id"] for o in options if o["source_key"] in sources and not o["prohibited"]]
        if expectation is None or expectation.optional:
            expected.append("NONE")
        elif not expected:
            expected = ["NOT_RETRIEVED"]
        cases.append(({"target": field(mapping.target), "candidates": options}, expected))
    return cases


def _row(system, payload, answer, expected=None):
    row = {
        "messages": [
            system,
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            {"role": "assistant", "content": json.dumps({"candidate_id": answer}, separators=(",", ":"))},
        ]
    }
    return {**row, "expected": expected} if expected else row


def _training(cases, system, rng) -> list[dict]:
    positives = [(p, e[0]) for p, e in cases if e[0] not in ("NONE", "NOT_RETRIEVED")]
    abstentions = [(p, "NONE") for p, e in cases if e == ["NONE"]]
    chosen = positives + rng.sample(abstentions, min(len(abstentions), len(positives)))
    return [_rebuild(_row(system, payload, answer), [], rng) for payload, answer in chosen]


def _identity(row) -> str:
    """A packet's content regardless of candidate order and IDs; renamed copies can leave fields unchanged."""
    payload = json.loads(row["messages"][1]["content"])
    candidates = sorted(
        json.dumps({k: v for k, v in c.items() if k != "candidate_id"}, sort_keys=True) for c in payload["candidates"]
    )
    return json.dumps([payload["target"], candidates], sort_keys=True)


def _test(cases, system, rng) -> list[dict]:
    answered = [(p, e) for p, e in cases if e != ["NONE"]]
    abstentions = [(p, e) for p, e in cases if e == ["NONE"]]
    chosen = answered + rng.sample(abstentions, min(len(abstentions), TEST_NONE))
    return [_row(system, payload, expected[0], expected) for payload, expected in chosen]


if __name__ == "__main__":
    main()
