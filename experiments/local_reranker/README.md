# Local candidate-selection fine-tuning experiment

This is an isolated MLX LoRA experiment for Apple Silicon. It does not change the
application's MiniLM configuration. Qwen evaluates candidate fields; it does not
replace the application's embedding encoder or execute generated transformations.

The [completed 20 October pilot](artifacts/2026-10-20-pilot/RESULTS.md) improved
origin recovery but introduced wrong suggestions compared with the current app.
Its saved adapter failed the promotion gate and is not active in the application.
A [repeat with Qwen3-1.7B-8bit](artifacts/2026-10-20-qwen3-1.7b/RESULTS.md), small enough for
GitHub LFS, failed the same gate by a wider margin (2 and 5 wrong public suggestions).
Prompts pass `enable_thinking=False`, which Qwen3 hybrid models need and the 4B template ignores.

The base is `mlx-community/Qwen3-4B-Instruct-2507-4bit`, revision
`50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b`. Supply an existing local copy with
`--model`. Training and inference block network connections.

## Data and selection

The frozen synthetic data contains 406 training examples, 68 validation examples
and 68 test examples. Training answers contain only a candidate ID or `NONE`.
Templates span identifiers, related records, labels, quantities, event times,
generated channel fields, ambiguity and absent evidence. Entity names and wording
differ across splits, but templates share structure: this is not independent
evidence of broad generalization. Some examples use value shape as evidence, so
the separate public-contract checks are necessary.
Training examples have two or three candidates and short definitions. Public
packets contain up to twelve candidates and substantially longer descriptions.
The pilot tests this transfer; it does not assume that success on the short
synthetic examples carries over to those larger packets.

The additional 16-case documentation challenge describes each API independently,
including numeric strings and misleading names. It is not used for training or
checkpoint selection. Labels are removed before inference. Every evaluation
reverses candidate order as a separate robustness check.

Checkpoints are selected by full validation loss, with the original base model
eligible to win. The evaluator never substitutes an unfinished adapter when the
base wins. Loss measures assistant response tokens and excludes prompt/padding.
A final validation evaluates the last actual weight update. Training completions
are the literal JSON answer plus EOS following the inference prefix. The base
tokenizer's full-chat rendering injects an empty thinking block for assistant
messages; that rendering is deliberately not used to construct training targets.

## Running

The tested runtime is Python 3.13, MLX 0.32.4, mlx-lm 0.32.2 and
Transformers 5.20.1. Use a separate environment from the application.

From the repository root:

```sh
python -m experiments.local_reranker.check_loss
python -m experiments.local_reranker.train \
  --model /absolute/path/to/Qwen3-4B-Instruct-2507-4bit \
  --data experiments/local_reranker/data \
  --output /absolute/path/to/a-new-run \
  --iterations 128 --eval-every 64
```

Every run requires a new output directory and preserves earlier attempts.
`selection.json` identifies the best evaluated checkpoint. If its `adapter` is
null, evaluate the base by omitting `--adapter`.

```sh
python -m experiments.local_reranker.evaluate \
  --model /absolute/path/to/Qwen3-4B-Instruct-2507-4bit \
  --adapter /absolute/path/to/a-new-run/selected \
  --data experiments/local_reranker/data/test.jsonl \
  --output /absolute/path/to/a-new-evaluation
```

Repeat without `--adapter` for the base, and with `docs-challenge.jsonl` for the
documentation challenge. `prepare_public` freezes the current application's
candidate retrieval and baseline on the repository's 99 public-contract labels.
It requires the application's optional NLP dependencies and `PYTHONPATH=.:src`.
Answer-key origins never influence candidate discovery or ranking.

For the complete bounded comparison, use a new evaluation directory:

```sh
PYTHONPATH=.:src python -m experiments.local_reranker.prepare_public \
  --output /absolute/path/to/evaluation/public-inputs
PYTHONPATH=.:src python -m experiments.local_reranker.evaluate_suite \
  --run /absolute/path/to/a-new-run \
  --output /absolute/path/to/evaluation
```

This preserves all six evaluations, including the original and reversed orders.
The public focus set is selected deterministically before either model is run.
The 99-case baseline uses the repository's published-contract fixtures, not live
authenticated downstream calls.

`normalize_docs` is a separate post-test diagnostic. It moves existing
documentation facts and citations into field descriptions, without changing
labels. Evaluate the resulting file with both models. Its result is exploratory;
it cannot replace the original held-out documentation result.

## Promotion gate

The first public comparison uses all eight currently missed origins plus two
correct origins and two correct abstentions per provider (16 cases total),
selected before evaluating the trained checkpoint. For each candidate order,
the adapter must produce zero wrong or invalid suggestions, retain all four
working origins, and recover at least one missed origin. It must also improve
selection accuracy over the base on the synthetic test and documentation challenge
without increasing wrong suggestions. Passing this gate warrants the full
99-case evaluation; it does not itself warrant deployment.

Any later app integration must retain compatibility checks, source provenance,
strict candidate IDs, abstention and human review. Lower training loss alone is
not grounds for replacing the model or accepting mappings automatically.
