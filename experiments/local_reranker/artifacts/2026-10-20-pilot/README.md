# Experimental Qwen candidate selector

This directory preserves an actual completed 128-step local LoRA pilot.
It is an experiment artifact, not the application's active model.

**It failed the promotion gate.** See [the completed evaluation](RESULTS.md)
before using these weights. They have not been activated or pushed.

The adapter contains 2,624,893 bytes. SHA-256:

```
9c7c8eb155772d37bb3157c08bf0d52bdf94b4bce1008fbd4bc5e41d5d5206ae
```

It requires the exact Qwen3-4B base identified in
[`../../base-model.json`](../../base-model.json). The 2.1 GiB base weights are
not included here. The original base model card identifies Apache-2.0 licensing.
The adapter is not usable by the application's MiniLM embedding loader.

`adapter/` can be supplied to the experiment evaluator's `--adapter` argument
with an explicit local `--model` path. Paths recorded in the training metadata
describe the original run; they do not need to exist on the destination machine.
Inference and training run offline.

`completion.json` proves the training loop finished and records a nonzero weight
change. `selection.json` records validation-based checkpoint selection.
`metrics.json` and `data-audit.json` preserve the training history and split hashes.
Mapping quality must be judged from the evaluation report, not the validation loss.
