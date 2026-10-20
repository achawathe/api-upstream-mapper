"""Measure what the optional local NLP model changes, benchmark by benchmark.

Runs every benchmark with rules only and with the model, then reports accuracy, how many
field decisions differ and the time taken. Requires the `nlp` extra and a local model folder.

    python tools/nlp_effect.py --nlp-model models/all-MiniLM-L6-v2
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from api_mapper.evaluation.answer_key import load_answer_key
from api_mapper.evaluation.grader import Outcome, grade
from api_mapper.matching.semantic import NlpSettings
from api_mapper.models import MappingRun
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
UPSTREAM = SAMPLES / "upstream/fdx/core-exchange-6.4.yaml"


@dataclass(frozen=True)
class Benchmark:
    name: str
    downstreams: tuple[Path, ...]
    answer_key: Path
    error_catalog: Path | None = None


BENCHMARKS = (
    Benchmark(
        "Northwind sample APIs",
        tuple(
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
        ),
        SAMPLES / "answer_key.yaml",
        SAMPLES / "upstream/fdx/error-catalog.yaml",
    ),
    Benchmark(
        "Held-out CDR",
        (SAMPLES / "held-out/cdr/cds_banking.json", SAMPLES / "held-out/cdr/cds_common.json"),
        SAMPLES / "held-out/cdr/answer_key.yaml",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nlp-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "nlp-effect.json")
    args = parser.parse_args()

    lexicon = Lexicon.load()
    nlp = NlpSettings(model_path=str(args.nlp_model.resolve()))
    rows = []
    for benchmark in BENCHMARKS:
        rules, rules_seconds = _run(benchmark, MappingPipeline(lexicon))
        model, model_seconds = _run(benchmark, MappingPipeline(lexicon, nlp=nlp))
        rows.append(
            {
                "benchmark": benchmark.name,
                "rules": _scores(benchmark, rules, rules_seconds),
                "nlp": _scores(benchmark, model, model_seconds),
                "decisions_changed": _changed(rules, model),
            }
        )
    for row in rows:
        print(
            f"{row['benchmark']}: {row['decisions_changed']} decisions changed | "
            f"rules {row['rules']['summary']} | nlp {row['nlp']['summary']}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2))


def _run(benchmark: Benchmark, pipeline: MappingPipeline) -> tuple[MappingRun, float]:
    started = perf_counter()
    inputs = pipeline.load(UPSTREAM, list(benchmark.downstreams), benchmark.error_catalog)
    return pipeline.run(inputs).run, perf_counter() - started


def _scores(benchmark: Benchmark, run: MappingRun, seconds: float) -> dict:
    report = grade(run.mappings, load_answer_key(benchmark.answer_key, run.upstream.name))
    wrong = report.counts[Outcome.WRONG_AUTO] + report.counts[Outcome.SPURIOUS_AUTO]
    return {
        "precision": round(report.auto_precision, 4),
        "recall": round(report.recall, 4),
        "automatic_recall": round(report.auto_recall, 4),
        "wrong_automatic": wrong,
        "seconds": round(seconds, 2),
        "summary": (
            f"precision {report.auto_precision:.1%}, recall {report.recall:.1%}, {wrong} wrong auto, {seconds:.1f}s"
        ),
    }


def _changed(left: MappingRun, right: MappingRun) -> int:
    def decision(run: MappingRun) -> dict[str, tuple]:
        return {m.target.key: (m.status, m.chosen.source.key if m.chosen else None) for m in run.mappings}

    a, b = decision(left), decision(right)
    return sum(1 for key in a if a[key] != b.get(key))


if __name__ == "__main__":
    main()
