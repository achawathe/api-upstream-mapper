"""Compare completed evaluations against the frozen promotion gate, with each order kept separate."""

import argparse
import json
from pathlib import Path

from experiments.local_reranker.runtime import write_json


def decision(root: Path) -> dict:
    results = {}
    reasons = []
    for dataset in ("heldout", "docs", "public"):
        base = json.loads((root / f"base-{dataset}" / "summary.json").read_text())
        trained = json.loads((root / f"trained-{dataset}" / "summary.json").read_text())
        results[dataset] = {"base": base, "trained": trained}
        for order in ("original", "reversed"):
            old, new = base[order], trained[order]
            if old["cases"] != new["cases"]:
                raise ValueError("Cannot compare different test populations")
            if dataset == "public":
                if new["wrong"] or new["invalid"] or new["correct"] < 5:
                    reasons.append(
                        f"{dataset}/{order}: needs zero wrong/invalid choices and at least five correct origins"
                    )
            elif (
                new["wrong"] > old["wrong"]
                or new["invalid"]
                or new["correct"] + new["abstained"] <= old["correct"] + old["abstained"]
            ):
                reasons.append(f"{dataset}/{order}: selection accuracy must improve without additional wrong choices")
        if dataset == "public":
            rows = json.loads((root / "trained-public" / "results.json").read_text())
            manifest = json.loads((root / "public-inputs" / "focused-manifest.json").read_text())
            controls = {index for index, case in enumerate(manifest["cases"]) if case["baseline"] and case["expected"]}
            if any(row["case"] in controls and row["outcome"] != "correct" for row in rows):
                reasons.append("public: an existing correct origin was lost")
    return {
        "passes_focused_gate": not reasons,
        "reasons": reasons,
        "results": results,
        "deployment": "Never automatic; a pass requires the full public-contract evaluation and integration checks",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = decision(args.root)
    write_json(args.root / "comparison.json", result)
    print(json.dumps(result, indent=2))
