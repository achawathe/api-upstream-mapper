# Qwen3-1.7B-8bit trained on app-built packets — 20 October 2026

**Decision: not promoted, and the 1.7B reranker line stops here. On CDR, an API set no model had seen, the trained model was wrong on 39–54% of packets; the application's own suggestions on the same packets are wrong on 9.5%.**

The [shuffled run](../2026-10-20-qwen3-1.7b-shuffled/RESULTS.md) showed that synthetic templates do not teach real field meaning. This run trained on packets the application builds itself, with [prepare_keyed.py](../../prepare_keyed.py):

- **Train:** the eight Northwind APIs plus four renamed copies from the stress generators (lexicon seeds 0–1, hard seeds 0–1), labelled from `samples/answer_key.yaml`. The application's retrieval supplied up to 12 candidates; candidates were shuffled with random IDs; required targets whose source was not retrieved were skipped; abstentions were capped at the number of positives. 1,536 rows, 28% `NONE`.
- **Validation:** hard seed 9, with two packets identical to training packets removed after the data audit flagged them. 303 rows; 100 used per evaluation.
- **Fresh test:** 179 CDR packets built the same way from the CDR answer key: all 139 targets with a source, plus 40 sampled no-source targets.

Training: 768 updates, `--max-length 2048`, other settings unchanged. 2,862 s, peak 3.87 GB, validation loss 0.724 to 0.167, final checkpoint selected.

## Results

Wrong rate is wrong choices divided by cases. [tolerance.json](eval/tolerance.json) applies the user's bar (at most 10% wrong per set and order, no invalid answers, no lost working origins, more public origins than the app's 4).

| Set / order | Correct | Wrong | Missed | Correct abstentions | Invalid | Wrong rate |
|---|---:|---:|---:|---:|---:|---:|
| **CDR (fresh) / app suggestions** | 122 | 17 | 1 | 39 | 0 | **9.5%** |
| CDR / 1.7B base, original | 64 | 94 | 2 | 18 | 1 | 52.5% |
| CDR / 1.7B base, reversed | 72 | 84 | 3 | 16 | 4 | 46.9% |
| **CDR / trained, original** | 97 | 70 | 1 | 10 | 1 | **39.1%** |
| **CDR / trained, reversed** | 62 | 97 | 2 | 16 | 2 | **54.2%** |
| Public / app | 4 | 0 | 8 | 4 | 0 | 0% |
| Public / trained, original | 6 | 4 | 3 | 3 | 0 | 25.0% |
| Public / trained, reversed | 4 | 5 | 6 | 1 | 0 | 31.2% |
| Docs challenge / trained, original | 1 | 1 | 6 | 8 | 0 | 6.2% |
| Docs challenge / trained, reversed | 2 | 4 | 3 | 7 | 0 | 25.0% |
| Synthetic test / trained, original | 4 | 11 | 22 | 31 | 0 | 16.2% |
| Synthetic test / trained, reversed | 2 | 17 | 22 | 27 | 0 | 25.0% |

The app row for CDR counts its automatic and review choices on exactly these 179 targets; all 17 of its wrong choices are review suggestions, none automatic. Changed choices after reversing candidates: CDR 107 of 179, public 10, docs 4, synthetic 15.

The trained model's CDR mistakes are real, not label noise. Of 70 wrong choices in original order, 32 picked a source for a target with none, 21 picked the wrong source for an optional target and 17 for a required one. A sample shows the pattern: the right field name from the wrong record, such as the account list's `nickname` for a single-account `nickname`, or a repayment schedule's `dueDate` for `nextPaymentDate`. The rules already separate those cases with record and collection penalties.

## Across the three 1.7B runs

| Run | Training data | Public wrong (orig / rev) | Public correct | Outcome |
|---|---|---|---|---|
| [1](../2026-10-20-qwen3-1.7b/RESULTS.md) | frozen synthetic, 2–3 candidates | 2 / 5 | 6 / 6 | position bias |
| [2](../2026-10-20-qwen3-1.7b-shuffled/RESULTS.md) | synthetic, shuffled, up to 12 | 1 / 1 | 2 / 0 | abstains almost always |
| 3 | app-built Northwind packets | 4 / 5 | 6 / 4 | wrong record, order-sensitive |

No run met the bar. A 1.7B model trained on what is available here either guesses by position, refuses, or ignores record ownership, and its answers change with candidate order. Training improves on the untrained base (CDR wrong 39–54% against 47–53%), but stays four to five times worse than the rules.

## Recommendation

Keep the application as it is: rules, with optional MiniLM. It already meets the 5–10% tolerance without a generative model: zero wrong automatic mappings on every benchmark, and 9.5% wrong review suggestions on the fresh CDR packets. The 1.83 GB base can be deleted from `~/models/Qwen3-1.7B-8bit`; nothing in the repository needs it.
