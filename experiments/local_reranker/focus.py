"""Freeze missed origins and a small set of working controls before model evaluation."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from experiments.local_reranker.runtime import write_json


def write_focus(output: Path, rows: list[dict], metadata: list[dict]) -> None:
    selected, cases = [], []
    counts = Counter()
    for row, case in zip(rows, metadata, strict=True):
        expected, chosen = case["expected"], case["baseline"]
        outcome = "correct" if chosen in expected else "wrong" if chosen else "missed" if expected else "abstained"
        key = (case["provider"], outcome)
        if outcome == "wrong" or (outcome != "missed" and counts[key] >= 2):
            continue
        counts[key] += 1
        selected.append(row)
        cases.append(case)
    path = output / "focused-public.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in selected))
    write_json(
        output / "focused-manifest.json",
        {
            "selection": "All currently missed origins plus first two correct origins and "
            "two correct abstentions per provider, before model evaluation.",
            "counts": {str(key): count for key, count in counts.items()},
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "cases": cases,
        },
    )
