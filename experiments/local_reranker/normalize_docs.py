"""Post-test diagnostic: move the same API facts into the trained description format."""

import argparse
import json
from pathlib import Path

from experiments.local_reranker.runtime import read_rows, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = read_rows(args.data)
    for row in rows:
        payload = json.loads(row["messages"][1]["content"])
        for field in [payload["target"], *payload["candidates"]]:
            docs = field.pop("documentation", [])
            field["description"] = " ".join(
                [
                    field.get("description", ""),
                    *(f"{clue['text']} (Source: {clue['location']})" for clue in docs),
                ]
            )
        row["messages"][1]["content"] = json.dumps(payload, separators=(",", ":"))
    with args.output.open("x") as stream:
        stream.writelines(json.dumps(row) + "\n" for row in rows)
    write_json(
        args.output.with_suffix(".protocol.json"),
        {
            "purpose": "Post-test representation diagnostic; not a fresh held-out evaluation.",
            "change": "Move existing documentation text and citations into each field description.",
            "preserved": "All API facts, candidate IDs, expected answers and case order.",
        },
    )


if __name__ == "__main__":
    main()
