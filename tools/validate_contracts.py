"""Run the frozen real-contract benchmark with network access disabled during inference."""

import argparse
import json
import os
import socket
from pathlib import Path
from time import perf_counter

from api_mapper.evaluation.contracts import grade_contract
from api_mapper.matching.semantic import NlpSettings
from api_mapper.normalize.lexicon import Lexicon
from api_mapper.pipeline.orchestrator import MappingPipeline

ROOT = Path(__file__).resolve().parents[1]


def forbid_network(*args, **kwargs):
    raise RuntimeError("network access is disabled during contract validation")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nlp-model", help="complete local Sentence Transformers model folder")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "real-contracts.json")
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    socket.socket.connect = forbid_network
    socket.create_connection = forbid_network
    fixtures = ROOT / "samples" / "real-contracts"
    labels = json.loads((fixtures / "answer-key.json").read_text())
    lexicon = Lexicon.load(ROOT / "lexicon" / "finance.yaml")
    modes = {"rules": None}
    if args.nlp_model:
        modes["local_nlp"] = NlpSettings(model_path=args.nlp_model)
    reports = []
    for mode, settings in modes.items():
        pipeline = MappingPipeline(lexicon, nlp=settings)
        for provider in sorted({row["provider"] for row in labels}):
            started = perf_counter()
            loaded = pipeline.load(
                ROOT / "samples/upstream/fdx/core-exchange-6.4.yaml", [fixtures / provider / "openapi.json"]
            )
            result = pipeline.run(loaded)
            scoped = [row for row in labels if row["provider"] == provider]
            report = grade_contract(result.run.mappings, scoped, set(result.prepared.sources))
            reports.append(
                {
                    "mode": mode,
                    "provider": provider,
                    "summary": report.summary,
                    "seconds": round(perf_counter() - started, 3),
                    "rows": report.rows,
                }
            )
            print(mode, provider, json.dumps(report.summary), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, indent=2) + "\n")


if __name__ == "__main__":
    main()
