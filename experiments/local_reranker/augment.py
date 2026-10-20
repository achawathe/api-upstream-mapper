"""Write a training set with longer, shuffled candidate lists so the answer cannot follow position or ID.

Each frozen example is kept once with its candidates shuffled, then repeated with distractors
taken from unrelated examples, up to twelve candidates. IDs are renumbered in random order, so
neither an ID nor a position says anything about the answer. Distractors whose description
shares most of its words with the target are skipped, since they could be a genuine origin.
Packets built from response examples are only shuffled, because their examples are keyed by
the original candidates. The test split is copied unchanged; validation is augmented the same
way, with its own seed, for checkpoint selection.
"""

import argparse
import json
import random
import re
from pathlib import Path

from experiments.local_reranker.runtime import read_rows

MAX_CANDIDATES = 12
MAX_OVERLAP = 0.3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--copies", type=int, default=2)
    parser.add_argument("--seed", type=int, default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for offset, split in enumerate(("train", "valid")):
        rows = read_rows(args.data / f"{split}.jsonl")
        augmented = augment(rows, args.copies, random.Random(args.seed + offset))
        _write(args.output / f"{split}.jsonl", augmented)
    (args.output / "test.jsonl").write_bytes((args.data / "test.jsonl").read_bytes())


def augment(rows: list[dict], copies: int, rng: random.Random) -> list[dict]:
    pool = [
        (index, candidate)
        for index, row in enumerate(rows)
        if "target" in _payload(row)
        for candidate in _payload(row)["candidates"]
    ]
    result = []
    for index, row in enumerate(rows):
        result.append(_rebuild(row, [], rng))
        payload = _payload(row)
        if "target" not in payload:
            continue
        for _ in range(copies):
            wanted = rng.randint(len(payload["candidates"]), MAX_CANDIDATES) - len(payload["candidates"])
            extras = _distractors(pool, index, payload["target"], wanted, rng)
            result.append(_rebuild(row, extras, rng))
    rng.shuffle(result)
    return result


def _distractors(pool, index, target, wanted, rng):
    chosen, seen = [], set()
    for other, candidate in rng.sample(pool, len(pool)):
        if len(chosen) == wanted:
            break
        key = (candidate["path"], candidate["description"])
        if other == index or key in seen or _overlap(candidate["description"], target["description"]) > MAX_OVERLAP:
            continue
        seen.add(key)
        chosen.append(candidate)
    return chosen


def _rebuild(row, extras, rng):
    system, user, answer = row["messages"]
    payload = json.loads(user["content"])
    expected = json.loads(answer["content"])["candidate_id"]
    tagged = [(candidate, candidate["candidate_id"] == expected) for candidate in payload["candidates"]]
    tagged += [(candidate, False) for candidate in extras]
    rng.shuffle(tagged)
    numbers = rng.sample(range(1, len(tagged) + 1), len(tagged))
    candidates, choice = [], "NONE"
    for number, (candidate, correct) in zip(numbers, tagged, strict=True):
        candidates.append({**candidate, "candidate_id": f"C{number}"})
        if correct:
            choice = f"C{number}"
    payload["candidates"] = candidates
    return {
        "messages": [
            system,
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            {"role": "assistant", "content": json.dumps({"candidate_id": choice}, separators=(",", ":"))},
        ]
    }


def _payload(row):
    return json.loads(row["messages"][1]["content"])


def _overlap(left: str, right: str) -> float:
    a, b = set(re.findall(r"[a-z0-9]+", left.lower())), set(re.findall(r"[a-z0-9]+", right.lower()))
    return len(a & b) / len(a | b) if a | b else 0.0


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))


if __name__ == "__main__":
    main()
