"""Run a bounded local LoRA experiment in a fresh directory, without modifying base weights."""

import argparse
import hashlib
import importlib.metadata
from pathlib import Path

from experiments.local_reranker.runtime import offline, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=128)
    parser.add_argument("--validation-batches", type=int, default=-1)
    parser.add_argument("--eval-every", type=int, default=64)
    parser.add_argument("--layers", type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    offline()
    import mlx.core as mx
    import mlx.optimizers as optim
    import numpy as np
    from mlx.utils import tree_flatten
    from mlx_lm import load
    from mlx_lm.tuner.datasets import CacheDataset
    from mlx_lm.tuner.trainer import TrainingArgs, evaluate, train
    from mlx_lm.tuner.utils import linear_to_lora_layers

    from experiments.local_reranker.audit import audit
    from experiments.local_reranker.checkpoints import Recorder
    from experiments.local_reranker.dataset import SelectionDataset
    from experiments.local_reranker.loss import answer_loss

    mx.random.seed(12)
    np.random.seed(12)
    mx.set_cache_limit(256 * 1024**2)
    model, tokenizer = load(str(args.model.resolve()), tokenizer_config={"trust_remote_code": False})
    write_json(args.output / "data-audit.json", audit(args.data, tokenizer, 512))
    config = {
        "model": str(args.model.resolve()),
        "data": str(args.data.resolve()),
        "fine_tune_type": "lora",
        "num_layers": args.layers,
        "lora_parameters": {
            "rank": 8,
            "scale": 16.0,
            "dropout": 0.05,
            "keys": ["self_attn.q_proj", "self_attn.v_proj"],
        },
        "mask_prompt": True,
        "train": True,
        "test": False,
        "seed": 12,
        "iterations": args.iterations,
        "learning_rate": 5e-5,
        "max_seq_length": 512,
        "validation_batches": args.validation_batches,
        "completion_format": "inference prefix + literal JSON + EOS; no template-inserted reasoning",
        "eval_every": args.eval_every,
        "versions": {p: importlib.metadata.version(p) for p in ("mlx", "mlx-lm", "transformers")},
    }
    write_json(args.output / "adapter_config.json", config)
    train_set = SelectionDataset(args.data / "train.jsonl", tokenizer)
    valid_set = SelectionDataset(args.data / "valid.jsonl", tokenizer)
    model.freeze()
    linear_to_lora_layers(model, args.layers, config["lora_parameters"])
    initial = dict(tree_flatten(model.trainable_parameters()))
    mx.eval(initial)
    recorder = Recorder(model, args.output)
    settings = TrainingArgs(
        batch_size=1,
        iters=args.iterations,
        val_batches=args.validation_batches,
        steps_per_report=1 if args.iterations <= 4 else 8,
        steps_per_eval=args.eval_every,
        steps_per_save=args.eval_every,
        adapter_file=args.output / "adapters.safetensors",
        max_seq_length=512,
        grad_checkpoint=True,
        clear_cache_threshold=256 * 1024**2,
    )
    train(
        model,
        optim.Adam(learning_rate=5e-5),
        CacheDataset(train_set),
        CacheDataset(valid_set),
        args=settings,
        loss=answer_loss,
        training_callback=recorder,
    )
    final_loss = evaluate(model, CacheDataset(valid_set), 1, args.validation_batches, 512, loss=answer_loss)
    recorder.on_val_loss_report({"iteration": args.iterations, "val_loss": final_loss, "final": True})
    delta = sum(
        float(mx.sum(mx.abs(value - initial[name]))) for name, value in tree_flatten(model.trainable_parameters())
    )
    adapter = args.output / "adapters.safetensors"
    write_json(
        args.output / "completion.json",
        {
            "iterations": args.iterations,
            "parameter_change_l1": delta,
            "adapter_bytes": adapter.stat().st_size,
            "adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
            "peak_memory_gb": mx.get_peak_memory() / 1e9,
        },
    )
    print("TRAINING_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
