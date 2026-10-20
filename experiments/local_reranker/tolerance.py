"""Check a completed evaluation against a bounded error rate for review suggestions.

The frozen gate in compare.py allows no wrong public suggestion. Suggestions only ever reach
a reviewer, so this check accepts up to a stated share of wrong choices per dataset and
candidate order instead. Invalid answers and lost working origins still fail outright, and
the trained model must find more public origins than the current app.
"""

import argparse
import json
from pathlib import Path

from experiments.local_reranker.runtime import write_json

APP_PUBLIC_CORRECT = 4


def check(root: Path, max_wrong: float) -> dict:
    reasons, rates = [], {}
    for dataset in ("heldout", "docs", "public"):
        summary = json.loads((root / f"trained-{dataset}" / "summary.json").read_text())
        for order in ("original", "reversed"):
            counts = summary[order]
            rate = counts["wrong"] / counts["cases"]
            rates[f"{dataset}/{order}"] = round(rate, 4)
            if rate > max_wrong:
                reasons.append(f"{dataset}/{order}: {counts['wrong']} of {counts['cases']} wrong ({rate:.1%})")
            if counts["invalid"]:
                reasons.append(f"{dataset}/{order}: {counts['invalid']} invalid answers")
            if dataset == "public" and counts["correct"] <= APP_PUBLIC_CORRECT:
                reasons.append(f"public/{order}: {counts['correct']} correct origins, the app already finds 4")
    rows = json.loads((root / "trained-public" / "results.json").read_text())
    manifest = json.loads((root / "public-inputs" / "focused-manifest.json").read_text())
    controls = {index for index, case in enumerate(manifest["cases"]) if case["baseline"] and case["expected"]}
    if any(row["case"] in controls and row["outcome"] != "correct" for row in rows):
        reasons.append("public: an existing correct origin was lost")
    return {"max_wrong": max_wrong, "passes": not reasons, "reasons": reasons, "wrong_rates": rates}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--max-wrong", type=float, default=0.10)
    args = parser.parse_args()
    result = check(args.root, args.max_wrong)
    write_json(args.root / "tolerance.json", result)
    print(json.dumps(result, indent=2))
