"""Evaluate a completed training run sequentially, preserving all results and the explicit base fallback."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from experiments.local_reranker.compare import decision
from experiments.local_reranker.runtime import write_json

DATA = Path(__file__).resolve().parent / "data"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (args.run / "completion.json").is_file():
        raise ValueError("Training has not completed; do not evaluate an unfinished run")
    config = json.loads((args.run / "adapter_config.json").read_text())
    selection = json.loads((args.run / "selection.json").read_text())
    datasets = {
        "docs": DATA / "docs-challenge.jsonl",
        "heldout": DATA / "test.jsonl",
        "public": args.output / "public-inputs/focused-public.jsonl",
    }
    for name, dataset in datasets.items():
        for label, adapter in (("base", None), ("trained", selection["adapter"])):
            stage = f"{label}-{name}"
            command = [
                sys.executable,
                "-m",
                "experiments.local_reranker.evaluate",
                "--model",
                config["model"],
                "--data",
                str(dataset),
                "--output",
                str(args.output / stage),
            ]
            if adapter:
                command.extend(["--adapter", adapter])
            print("START", stage, flush=True)
            with (args.output / f"{stage}.log").open("x") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            print("COMPLETE", stage, (args.output / stage / "summary.json").read_text(), flush=True)
    result = decision(args.output)
    write_json(args.output / "comparison.json", result)
    print(
        "EXPERIMENT_EVALUATION_COMPLETE",
        "focused gate passed" if result["passes_focused_gate"] else "do not promote",
        flush=True,
    )


if __name__ == "__main__":
    main()
