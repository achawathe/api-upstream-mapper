"""Audit the exact chat template, completion boundaries, split isolation and token limits."""

import hashlib
import json
from pathlib import Path

from experiments.local_reranker.dataset import completion_tokens
from experiments.local_reranker.runtime import read_rows


def audit(data: Path, tokenizer, max_tokens: int) -> dict:
    report, inputs = {}, {}
    for split in ("train", "valid", "test"):
        path = data / f"{split}.jsonl"
        rows = read_rows(path)
        lengths, answer_lengths = [], []
        inputs[split] = set()
        for row in rows:
            messages = row["messages"]
            prompt = tokenizer.apply_chat_template(
                messages[:-1], add_generation_prompt=True, return_dict=False, enable_thinking=False
            )
            full, offset = completion_tokens(row, tokenizer)
            if full[: len(prompt)] != prompt:
                raise ValueError("Training and inference chat prefixes differ")
            if offset != len(prompt) or tokenizer.decode(full[offset:-1]) != messages[-1]["content"]:
                raise ValueError("Training completion is not exactly the requested JSON")
            answer = json.loads(messages[-1]["content"])
            payload = json.loads(messages[1]["content"])
            allowed = {candidate["candidate_id"] for candidate in payload["candidates"]} | {"NONE"}
            if set(answer) != {"candidate_id"} or answer["candidate_id"] not in allowed:
                raise ValueError("Training answer is outside the selection-only contract")
            if len(full) > max_tokens or len(full) <= len(prompt):
                raise ValueError("Example truncates or contains no answer tokens")
            lengths.append(len(full))
            answer_lengths.append(len(full) - len(prompt))
            inputs[split].add(messages[1]["content"])
        report[split] = {
            "rows": len(rows),
            "max_tokens": max(lengths),
            "min_answer_tokens": min(answer_lengths),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    if any(inputs[a] & inputs[b] for a, b in (("train", "valid"), ("train", "test"), ("valid", "test"))):
        raise ValueError("Exact input overlap between splits")
    return report
