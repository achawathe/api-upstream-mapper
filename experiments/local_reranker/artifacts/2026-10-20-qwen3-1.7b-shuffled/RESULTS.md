# Qwen3-1.7B-8bit with shuffled, longer candidate lists — 20 October 2026

**Decision: not promoted. Order sensitivity mostly went away, but the model learned to abstain: it found fewer public origins than the current app.**

The [first 1.7B run](../2026-10-20-qwen3-1.7b/RESULTS.md) trained on two- or three-candidate packets and made most of its public mistakes by picking the first candidate shown. This run changed only the training data and length, using [augment.py](../../augment.py):

- every frozen training and validation packet kept once, with candidates shuffled and IDs renumbered at random;
- each description-style packet repeated twice with distractors from unrelated examples, up to 12 candidates (distractors sharing more than 30% of the target description's words were skipped);
- 1,054 training rows, 59% `NONE`, answers spread over C1–C12; validation augmented the same way for checkpoint selection, test split unchanged.

Training: 1,054 updates (one pass), `--max-length 1024`, otherwise the same settings. 2,180 s, peak 3.31 GB, validation loss 1.246 to 0.127, final checkpoint selected.

## Results

Wrong rate is wrong choices divided by cases. The bar the user set is at most 10% per set and order, with no invalid answers, no lost working origins, and more public origins than the app's 4. [tolerance.json](eval/tolerance.json) has the check; the frozen gate is in [eval/comparison.json](eval/comparison.json).

| Set / order | Correct | Wrong | Missed | Correct abstentions | Invalid | Wrong rate |
|---|---:|---:|---:|---:|---:|---:|
| Public / original | 2 | 1 | 10 | 3 | 0 | 6.3% |
| Public / reversed | 0 | 1 | 11 | 3 | 1 | 6.3% |
| Docs challenge / original | 0 | 0 | 7 | 9 | 0 | 0% |
| Docs challenge / reversed | 0 | 0 | 7 | 9 | 0 | 0% |
| Synthetic test / original | 8 | 12 | 15 | 33 | 0 | 17.6% |
| Synthetic test / reversed | 9 | 9 | 17 | 33 | 0 | 13.2% |

Changed choices after reversing candidates: public 4 (first 1.7B run: 8), docs 0 (12), synthetic 7 (17).

Both checks fail. The low wrong rates on public and docs come from answering `NONE` almost everywhere: the model found 2 and 0 public origins where the app finds 4, lost working control origins, and found nothing on the docs challenge. On the synthetic test, wrong choices stayed above 10%.

## What it shows

Shuffling candidates and IDs removes most of the order sensitivity. It does not teach the model what real field descriptions mean: the synthetic templates are too far from the public contracts, and with long unfamiliar lists the safest learned answer is `NONE`. The next run trains on packets the app itself builds from labelled downstreams.
