"""Evaluate frozen selections in both candidate orders; labels never enter model prompts."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from experiments.local_reranker.runtime import offline, read_rows, write_json


def parse_choice(raw: str, payload: dict) -> str | None:
    allowed = {c["candidate_id"] for c in payload["candidates"] if not c.get("prohibited")} | {"NONE"}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"candidate_id"}:
        return None
    choice = parsed["candidate_id"]
    return choice if isinstance(choice, str) and choice in allowed else None


def summary(results: list[dict]) -> dict:
    totals = {}
    for order in ("original", "reversed"):
        rows = [row for row in results if row["order"] == order]
        totals[order] = {
            key: sum(row["outcome"] == key for row in rows)
            for key in ("correct", "wrong", "missed", "abstained", "invalid")
        }
        totals[order]["cases"] = len(rows)
        totals[order]["seconds"] = round(sum(row["seconds"] for row in rows), 2)
    originals = {row["case"]: row["actual"] for row in results if row["order"] == "original"}
    totals["order_changes"] = sum(
        row["actual"] != originals[row["case"]] for row in results if row["order"] == "reversed"
    )
    return totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    offline()
    import mlx.core as mx
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_sampler

    if args.adapter and not (args.adapter / "adapters.safetensors").is_file():
        raise ValueError("The selected adapter has no trained weights")
    model, tokenizer = load(
        str(args.model),
        adapter_path=str(args.adapter) if args.adapter else None,
        tokenizer_config={"trust_remote_code": False},
    )
    mx.set_cache_limit(256 * 1024**2)
    rows = read_rows(args.data)[: args.limit]
    write_json(
        args.output / "protocol.json",
        {
            "model": str(args.model),
            "adapter": str(args.adapter) if args.adapter else None,
            "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
            "limit": args.limit,
            "max_tokens": 32,
            "temperature": 0,
            "seed": 0,
            "network": "blocked",
            "selection": "No labels in prompts; all choices require review",
        },
    )
    results = []
    for order in ("original", "reversed"):
        for index, row in enumerate(rows):
            messages = row["messages"][:-1]
            payload = json.loads(messages[1]["content"])
            if order == "reversed":
                payload["candidates"].reverse()
            messages = [messages[0], {"role": "user", "content": json.dumps(payload, separators=(",", ":"))}]
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
            mx.random.seed(0)
            started = time.perf_counter()
            chunks = list(stream_generate(model, tokenizer, prompt=prompt, max_tokens=32, sampler=make_sampler(temp=0)))
            raw = "".join(chunk.text for chunk in chunks)
            actual = parse_choice(raw, payload)
            expected = row.get("expected") or [json.loads(row["messages"][-1]["content"])["candidate_id"]]
            outcome = (
                "invalid"
                if actual is None
                else "abstained"
                if actual == "NONE" and "NONE" in expected
                else "correct"
                if actual in expected
                else "missed"
                if actual == "NONE"
                else "wrong"
            )
            result = {
                "case": index,
                "order": order,
                "actual": actual,
                "expected": expected,
                "outcome": outcome,
                "raw": raw,
                "seconds": round(time.perf_counter() - started, 3),
            }
            results.append(result)
            write_json(args.output / "results.json", results)
            print(index, order, outcome, flush=True)
            mx.clear_cache()
    write_json(args.output / "summary.json", summary(results))
    print("EVALUATION_COMPLETE", summary(results), flush=True)


if __name__ == "__main__":
    main()
