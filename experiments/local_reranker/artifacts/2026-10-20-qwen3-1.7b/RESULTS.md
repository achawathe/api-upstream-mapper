# Qwen3-1.7B-8bit against the pilot's promotion gate — 20 October 2026

**Decision: keep the current application model. The 1.7B adapter failed the frozen promotion gate, by a wider margin than the 4B pilot.**

This run followed [PLAN-qwen3-1.7b.md](../../PLAN-qwen3-1.7b.md): same data, training settings, public inputs and gate as the [4B pilot](../2026-10-20-pilot/RESULTS.md), with only the base model changed. The question was whether a base small enough for GitHub LFS (1.83 GB, under the 2 GB file cap) could pass where the 4B failed. It could not.

## What ran

- Base `mlx-community/Qwen3-1.7B-8bit`, revision `8c24f678…`, `model.safetensors` sha256 `91362cba…` verified after download. Hashes for every file are in [base-model-qwen3-1.7b.json](../../base-model-qwen3-1.7b.json). The base is not in the repository.
- Qwen3-1.7B is a hybrid model that thinks by default. All three prompt-rendering sites (`dataset.py`, `audit.py`, `evaluate.py`) now pass `enable_thinking=False`, which renders an empty think block before the answer. With the 4B tokenizer, all 68 validation prompts render to identical tokens with or without the argument, so the pilot stays reproducible. The plan named two of the three sites. The data audit caught the third on the first attempt, before any weight update; see [excluded-run.json](excluded-run.json).
- Smoke test on five test rows, base model: 10 of 10 answers were valid JSON within 32 tokens, about 0.6 s per case.
- Training: 128 updates, rank-8 LoRA on q/v in the last 8 of 28 layers, learning rate 5e-5, seed 12. 252 s wall time, peak MLX memory 2.67 GB (4B: 3.25 GB). Validation loss fell from 1.210 to 0.106 (4B: 2.249 to 0.098). The final checkpoint was selected; adapter 1.8 MB, sha256 `b2120e8d…`.
- Evaluation: [evaluate_suite](../../evaluate_suite.py) with the pilot's frozen public inputs, copied byte-for-byte (all five sha256 values match the pilot's provenance). Total 433 s for all six evaluations.
- The application tests for the experiment pass (4), and Ruff passes.

## Gate result

From [eval/comparison.json](eval/comparison.json):

- public/original: needs zero wrong/invalid choices and at least five correct origins
- public/reversed: needs zero wrong/invalid choices and at least five correct origins

All four working control origins were retained in both orders. The synthetic test and docs checks did not fail, but only because they compare against the 1.7B base, which is much weaker than the 4B base; see below.

## Public API focus set (16)

| Model / order | Correct origins | Wrong suggestions | Missed origins | Correct abstentions | Invalid |
|---|---:|---:|---:|---:|---:|
| Current app / original | 4 | 0 | 8 | 4 | 0 |
| 1.7B base / original | 5 | 3 | 5 | 3 | 0 |
| 1.7B base / reversed | 5 | 3 | 5 | 2 | 1 |
| **1.7B trained / original** | 6 | **2** | 5 | 3 | 0 |
| **1.7B trained / reversed** | 6 | **5** | 4 | 1 | 0 |
| 4B trained / original | 8 | 1 | 3 | 4 | 0 |
| 4B trained / reversed | 8 | 2 | 3 | 3 | 0 |

Changed choices after reversing candidates: 1.7B base 7, 1.7B trained 8, 4B trained 4.

The trained 1.7B's wrong suggestions:

| Order | Target | Chose | Expected |
|---|---|---|---|
| original | `productId` | `accounts[].account_id` | none |
| original | `transactions[].postedTimestamp` | `accounts[].balances.last_updated_datetime` | `transactions[].date` or `.datetime` |
| reversed | `productId` | `accounts[].account_id` | none |
| reversed | `status` | `item.error.status` | none |
| reversed | `paymentNetworks[].bankId` | `transactions[].payment_meta.ppd_id` | `numbers.ach[].routing` |
| reversed | `productName` | `Data.Account[].Account[].Name` | none |
| reversed | `statements[].description` | `...DeliveryAddress.TownName` | `Data.Statement[].StatementDescription[]` |

Five of the seven wrong choices are the first of 12 candidates in the order shown (C1 originally, C12 once reversed). That points to position bias, not field reasoning. `productId` to `account_id` is the same error the 4B made.

## Synthetic held-out cases (68)

| Model / order | Correct | Wrong | Missed | Correct abstentions | Invalid |
|---|---:|---:|---:|---:|---:|
| 1.7B base / original | 16 | 44 | 4 | 4 | 0 |
| 1.7B base / reversed | 10 | 53 | 3 | 2 | 0 |
| 1.7B trained / original | 12 | 13 | 7 | 36 | 0 |
| 1.7B trained / reversed | 8 | 16 | 7 | 37 | 0 |
| 4B trained / original | 15 | 11 | 7 | 35 | 0 |
| 4B trained / reversed | 13 | 13 | 5 | 37 | 0 |

Changed choices after reversing candidates: 1.7B base 29, 1.7B trained 17, 4B trained 15.

## Independent documentation challenge (16)

| Model / order | Correct | Wrong | Missed | Correct abstentions | Invalid |
|---|---:|---:|---:|---:|---:|
| 1.7B base / original | 4 | 12 | 0 | 0 | 0 |
| 1.7B base / reversed | 3 | 13 | 0 | 0 | 0 |
| 1.7B trained / original | 2 | 8 | 2 | 4 | 0 |
| 1.7B trained / reversed | 1 | 9 | 2 | 4 | 0 |
| 4B trained / original | 2 | 1 | 5 | 8 | 0 |
| 4B trained / reversed | 1 | 0 | 6 | 9 | 0 |

Changed choices after reversing candidates: 1.7B trained 12, 4B trained 4.

The gate passed this set for the 1.7B only because its base made 12–13 wrong choices out of 16, so 8–9 counted as an improvement. Against the 4B adapter (0–1 wrong), the 1.7B adapter is far worse on the one set written independently of the training data.

## What this means

- Model size matters here, in the wrong direction for portability: the 1.7B is worse than the 4B on every set, in both orders, and the 4B already failed.
- The training recipe teaches the answer format and abstention (the base's 44–53 synthetic wrong choices drop to 13–16), but not the field distinctions the gate tests. Lower validation loss than the 4B did not translate into accuracy, as the pilot warned.
- Inference is about 2.5 times faster than the 4B on the public set (50 s against 127 s for 16 cases in one order).
- A smaller base trained the same way is not a route to an accurate in-repo reranker. The pilot's own next-round recommendations (app-shaped packets, reviewed hard negatives, candidate order and ID variation, a fresh holdout) remain the untested options, and they apply to any base size.

## Saved artifacts and deployment state

- [Training run](run/) with [completion](run/completion.json), [selection](run/selection.json), [metrics](run/metrics.json) and [data audit](run/data-audit.json); the adapter is 1.8 MB, and `.gitattributes` stores it through LFS once committed.
- [All six evaluations and the gate decision](eval/comparison.json), each with prompts' data hash, raw outputs and summary.
- [Base smoke test](smoke-base/).

The application still uses `models/all-MiniLM-L6-v2` with similarity 0.8 and top_k 10. No app source changed. The base weights stay outside the repository at `~/models/Qwen3-1.7B-8bit`, and nothing was committed.
