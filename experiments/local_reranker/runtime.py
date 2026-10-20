"""Shared offline execution and artifact helpers for the isolated reranker experiment."""

import json
import os
import socket
from pathlib import Path


def offline() -> None:
    os.environ.update(
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", WANDB_MODE="disabled", TOKENIZERS_PARALLELISM="false"
    )
    socket.socket.connect = _blocked
    socket.create_connection = _blocked


def _blocked(*args, **kwargs):
    raise RuntimeError("Network access is disabled during this experiment")


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
