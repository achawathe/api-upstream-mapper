"""Save the exact validated adapter state; a winning base model remains an explicit null."""

import shutil
from pathlib import Path

import mlx.core as mx
from mlx.utils import tree_flatten
from mlx_lm.tuner.callbacks import TrainingCallback

from experiments.local_reranker.runtime import write_json


class Recorder(TrainingCallback):
    def __init__(self, model, output: Path):
        self.model = model
        self.output = output
        self.best = float("inf")
        self.history = []

    def record(self, kind, info):
        self.history.append({"kind": kind, **info})
        write_json(self.output / "metrics.json", self.history)
        print(kind, info, flush=True)

    def on_train_loss_report(self, info):
        self.record("train", info)

    def on_val_loss_report(self, info):
        self.record("validation", info)
        if info["val_loss"] >= self.best:
            return
        self.best = info["val_loss"]
        adapter = None
        if info["iteration"] > 0:
            selected = self.output / "selected"
            selected.mkdir(exist_ok=True)
            mx.save_safetensors(
                str(selected / "adapters.safetensors"), dict(tree_flatten(self.model.trainable_parameters()))
            )
            shutil.copy2(self.output / "adapter_config.json", selected / "adapter_config.json")
            adapter = str(selected.resolve())
        write_json(self.output / "selection.json", {**info, "adapter": adapter})
