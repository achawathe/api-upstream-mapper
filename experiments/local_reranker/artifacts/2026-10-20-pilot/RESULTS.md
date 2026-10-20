# Completed local fine-tuning pilot — 20 October 2026

**Decision: keep the current application model. The experimental adapter failed the frozen promotion gate.**

Actual Qwen3-4B LoRA training completed 128 updates locally, saved a 2.6 MB adapter, and reloaded it for all trained-model evaluations. The adapter recovered additional public-contract origins, but introduced wrong suggestions and remained sensitive to candidate order. This is a completed bounded pilot, not a production-ready fine-tune.

## What changed and was verified

- Corrected answer-token masking to exclude padding. The installed trainer's default boundary included a padding target.
- Constructed the training completion as the literal selection JSON plus EOS after the inference prefix. Full-chat rendering had inserted an empty thinking block and post-EOS text. The earlier 320-step attempt was interrupted at 112 reported updates and explicitly excluded; its artifact is not the evaluated model.
- Preserved the original base weights unchanged. Selected the corrected checkpoint using all 68 validation examples, with the unmodified base eligible to win.
- Completed 128 updates using rank-8 LoRA on q/v projections in the last eight layers, batch size one and learning rate 0.00005. This is fewer updates than a full pass through the 406 training examples.
- Validation token loss fell from 2.249076 to 0.098285; trained parameters changed. Peak MLX memory was 3.252 GB. Loss includes predictable JSON-format tokens and is not mapping accuracy.
- Ran the application test suite: **315 passed**, with one existing Starlette deprecation warning. Four focused experiment tests passed; Ruff passed. Public-focus selection and documentation normalization scripts reproduced their frozen inputs byte-for-byte.

## Evaluation protocol

All model inference ran locally with network connections blocked, temperature zero, a 32-token output limit and strict candidate-ID validation. Ground-truth answers were excluded from prompts. Original and reversed candidate orders are reported separately; they are paired robustness checks, not independent extra test cases.

Training used 406 synthetic examples; validation and test each contained 68. There was no exact input overlap, but synthetic splits share template families. No training example had a separate documentation array, and all had only two or three candidates. Public packets had up to twelve candidates and much longer definitions. Four focused cases required a correct candidate beyond C3, a candidate ID range absent from training labels. These are observed distribution gaps, not proof that any one gap caused every error.

The independent 16-case documentation challenge was excluded from training and checkpoint selection. The public comparison used the existing FDX 6.4, Plaid and UK Open Banking fixtures and answer key. It is a published-contract lineage evaluation, not a live authenticated API parity test or a new untouched benchmark.

The current app was run on all 99 public labels: **40 correct origins, zero wrong suggestions, eight misses and 51 correct abstentions**. The focused 16 cases were frozen before model inference: all eight misses, four working origins and four correct abstentions. Retrieval did not use expected answers. Only ten of twelve true origins were present in the focus candidate packets; two could not be recovered by any selector. Conditional origins count as correct lineage; joins, status filters, precision loss and currency choices still require review.

## Synthetic held-out cases (68)

| Model / order | Correct origins | Wrong suggestions | Missed origins | Correct abstentions | Invalid or prohibited |
|---|---:|---:|---:|---:|---:|
| base / original | 13 | 46 | 0 | 9 | 0 |
| base / reversed | 14 | 45 | 1 | 8 | 0 |
| trained / original | 15 | 11 | 7 | 35 | 0 |
| trained / reversed | 13 | 13 | 5 | 37 | 0 |

Changed choices after reversing candidates: base 18, trained 15.

## Independent API documentation challenge (16)

| Model / order | Correct origins | Wrong suggestions | Missed origins | Correct abstentions | Invalid or prohibited |
|---|---:|---:|---:|---:|---:|
| base / original | 4 | 5 | 2 | 5 | 0 |
| base / reversed | 6 | 4 | 1 | 5 | 0 |
| trained / original | 2 | 1 | 5 | 8 | 0 |
| trained / reversed | 1 | 0 | 6 | 9 | 0 |

Changed choices after reversing candidates: base 7, trained 4.

## Public API focus set (16)

| Model / order | Correct origins | Wrong suggestions | Missed origins | Correct abstentions | Invalid or prohibited |
|---|---:|---:|---:|---:|---:|
| Current app / original | 4 | 0 | 8 | 4 | 0 |
| base / original | 8 | 3 | 2 | 3 | 0 |
| base / reversed | 6 | 7 | 0 | 2 | 1 |
| trained / original | 8 | 1 | 3 | 4 | 0 |
| trained / reversed | 8 | 2 | 3 | 3 | 0 |

Changed choices after reversing candidates: base 8, trained 4.

## What the public failures mean

The trained adapter retained all four working control origins in both candidate orders. In the original order it additionally found the related transaction ID, current balance, available balance and statement description. However, it selected `authorized_datetime` for `postedTimestamp` despite the correct posted-time definition being present.

In reversed order it selected an account ID for a product ID that had no source, and `LocalAmount.Amount` for current balance instead of the labeled `Amount.Amount` source. It recovered posted time in that order, illustrating that identical facts can yield a different answer solely because candidates move.

The current app's zero wrong suggestions on this narrow set therefore became one or two with the adapter. More recovered origins alone does not satisfy the requested accuracy improvement. The frozen gate also failed on the reversed documentation challenge. The full 99-case trained-model evaluation and app integration were not started after that gate failure.

## Controlled documentation diagnostic

After the primary evaluation, the same 16 documentation cases were repeated with documentation text and source citations moved into each field's description. No facts, candidate IDs or expected answers changed. This is a post-test diagnostic, not a replacement held-out result.

| Model | Correct origins before, original / reversed | Correct origins after, original / reversed | Wrong suggestions after, original / reversed |
|---|---|---|---|
| Base | 4 / 6 | 5 / 5 | 5 / 5 |
| Trained | 2 / 1 | 1 / 0 | 1 / 0 |

Simply presenting documentation in the trained description field did not fix the failures. The experiment does not support treating input reformatting alone as the solution.

## Implications for the next training round

1. Build training packets through the same representation used by the app: separate API definitions and documentation, response samples, longer descriptions and variable candidate counts. Keep documentation as facts about each API, not hand-written mapping instructions.
2. Add reviewed positive/negative pairs that distinguish event roles, record ownership and amount/currency meaning. Include valid string-to-number origins and conditional origins, so abstaining does not become a substitute for learning those distinctions. The current 406-example set contains 240 NONE answers.
3. Diagnose the two missing-origin retrieval cases separately. A model cannot choose a source excluded before inference.
4. Vary both candidate order and IDs during training. Use fresh API/domain holdouts for the next acceptance test; these evaluated cases are now development evidence.
5. Preserve hard compatibility constraints, source provenance and human review. Require recovered origins without increased wrong suggestions before integrating a reranker. This pilot does not establish that a larger base or more iterations alone will solve the errors.

## Saved artifacts and deployment state

- [Adapter and training provenance](README.md)
- [Promotion decision and all primary summaries](comparison.json)
- [Frozen public cases](public-inputs/focused-manifest.json)
- [Training completion](completion.json)
- [Training history](metrics.json)
- [Application test log](tests.log)

Each evaluation folder contains the exact prompt-data hash, outputs, expected IDs and summary. The adapter requires the pinned local 2.1 GiB Qwen base; the base is not bundled. The run used the Apple Silicon MLX runtime documented in the experiment README.

The live app was checked after evaluation and still uses `models/all-MiniLM-L6-v2` with similarity 0.8 and top_k 10. This experiment did not activate or push the Qwen adapter, and did not change application source code.
