# Plan: Qwen3-1.7B-8bit against the pilot's promotion gate

Status: completed 20 October 2026. Failed the gate; see
[RESULTS.md](artifacts/2026-10-20-qwen3-1.7b/RESULTS.md). One deviation: `audit.py` also renders
prompts and needed the same `enable_thinking=False` change. The planned template-rendering test
was replaced by updating the existing unit test, since the app environment has no jinja2.

## Question

Can a base model small enough to ship with the repository pass the same frozen gate that the
Qwen3-4B pilot failed? If it passes, it becomes the candidate to commit through Git LFS so the
app works after a plain `git pull`. If it fails, nothing is committed and the app keeps MiniLM.

## Why this model

| | Qwen3-4B pilot base | Qwen3-1.7B-8bit |
|---|---|---|
| Hugging Face id | `mlx-community/Qwen3-4B-Instruct-2507-4bit` | `mlx-community/Qwen3-1.7B-8bit` |
| Revision | `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b` | `8c24f6782a91421513803ce527a27dcc560ab904` |
| `model.safetensors` | 2,263,022,417 bytes | 1,828,306,541 bytes (1.70 GiB) |
| sha256 | `2a73c6c2…` | `91362cba4bbb481560ef149af63d88f2a542071c4c63df919b6021afd9fdee7e` |
| Fits GitHub Free LFS 2 GB file cap | no | yes |
| Layers / quantisation | 36 / 4-bit | 28 / 8-bit, group size 64 |
| Chat mode | instruct only | hybrid: thinks unless told not to |

It is the largest Qwen3 MLX build under the 2 GB cap, and it runs on the existing MLX pipeline
without new dependencies. The 8-bit quantisation loses less than the 4B's 4-bit, but the model
has fewer than half the parameters, so expect it to be weaker, not stronger.

## What stays fixed

The run changes the base model only, so the result isolates model size:

- Data: the frozen `data/train.jsonl` (406), `valid.jsonl` (68), `test.jsonl` (68) and
  `docs-challenge.jsonl` (16). No edits, no new examples.
- Public focus set: reuse `artifacts/2026-10-20-pilot/public-inputs/` byte-for-byte (check the
  sha256 values in `focused-manifest.json`) instead of regenerating it.
- Training: rank-8 LoRA on q/v projections in the last 8 layers, scale 16, dropout 0.05, learning
  rate 5e-5, batch size 1, 128 iterations, eval every 64, seed 12, max length 512.
  Eight of 28 layers is a larger share than eight of 36; it stays at 8 for comparability.
- Inference: temperature 0, 32-token limit, strict candidate IDs, network blocked, original and
  reversed candidate order reported separately.
- Runtime: Python 3.13, MLX 0.32.4, mlx-lm 0.32.2, Transformers 5.20.1, in an environment
  separate from the app.

The pilot's own recommendations for the next round (app-shaped packets, more negative pairs,
order and ID variation) are deliberately not applied here. Mixing them in would make a pass or
fail impossible to attribute.

## Required code change

Qwen3-1.7B is a hybrid model: its chat template opens a `<think>` block unless
`enable_thinking=False` is passed. With the 32-token limit, thinking output would make almost
every answer invalid. Two call sites render prompts:

- `dataset.py`, `completion_tokens`: `tokenizer.apply_chat_template(..., enable_thinking=False)`
- `evaluate.py`, prompt rendering: the same argument.

The 4B instruct template should ignore the variable. Before training, render every row of
`valid.jsonl` with the 4B tokenizer with and without the argument and confirm the token ids are
identical, so the pilot remains reproducible. Then render one row with the 1.7B tokenizer and
confirm the prompt ends in an empty `<think>\n\n</think>\n\n` block, so the model answers directly.

Add `base-model-qwen3-1.7b.json` beside `base-model.json` with the revision and per-file
sha256 values, written from the downloaded folder.

## Steps

1. **Download once, outside the repository**, at the pinned revision, for example to
   `~/models/Qwen3-1.7B-8bit`. Verify the `model.safetensors` sha256 above. Write the provenance
   file.
2. **Template check** as described above. Add a focused test that the rendered 1.7B prompt has
   no open thinking block.
3. **Smoke test the base**: evaluate the first 5 rows of `test.jsonl` without an adapter.
   Every answer must parse as a candidate ID or `NONE` within 32 tokens. Stop and report if not.
4. **Loss check**: `python -m experiments.local_reranker.check_loss`.
5. **Train** into a new directory, `artifacts/2026-10-2x-qwen3-1.7b/run`. Record peak memory
   and wall time. Selection by full validation loss, base eligible to win, as in the pilot.
6. **Evaluate**: `evaluate_suite` with the copied public inputs. This produces base and trained
   results for `heldout`, `docs` and `public`, each in both candidate orders.
7. **Gate**: `compare.decision`, unchanged. It passes only if, in both orders:
   - public focus set: zero wrong, zero invalid, at least 5 correct origins (the app has 4),
     and every one of the 4 existing correct origins retained;
   - synthetic test and docs challenge: no more wrong choices than the 1.7B base, no invalid
     choices, and more correct choices plus correct abstentions than the 1.7B base.
8. **Write `RESULTS.md`** in the run's artifact folder in the pilot's format, with an extra
   column comparing against the 4B pilot's trained numbers, plus peak memory, training time and
   inference time per case.

## After the gate

- **Fail**: record the result, commit the results and adapter only (a few MB), and keep the
  base weights out of git. The README keeps saying the reranker is not active.
- **Pass**: this warrants the full 99-case public evaluation, as the pilot specified, and does
  not by itself warrant shipping. Only after that passes:
  - Commit the base to `models/qwen3-1.7b-8bit/` through LFS (`*.safetensors` is already
    tracked) with its licence file and provenance. Cost: 1.83 GB of the 10 GB monthly LFS
    download allowance on GitHub Free per machine that pulls it, about five machines a month.
  - App integration gets its own plan: suggestions on review items only, never automatic
    mappings, with compatibility checks, provenance and human review kept.

## Limits on what a pass would show

- The public focus set and docs challenge were already used to judge the 4B pilot, so they are
  development evidence now, not a fresh holdout. A pass here is weaker evidence than a pass on
  unseen APIs. The held-out CDR answer key in `samples/held-out/cdr/` could serve as that fresh
  holdout, but `prepare_public` would need extending to it; that is outside this plan unless
  requested.
- 128 updates is less than one pass over the training set, the same as the pilot.
- MLX runs on Apple Silicon only. A machine without it cannot use this model.
