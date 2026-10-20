"""Answer-only loss excludes both the prompt and padding after the complete response."""

import mlx.core as mx
from mlx import nn


def answer_loss(model, batch, lengths):
    inputs, targets = batch[:, :-1], batch[:, 1:]
    positions = mx.arange(1, batch.shape[1])
    mask = (positions >= lengths[:, 0:1]) & (positions < lengths[:, 1:])
    losses = nn.losses.cross_entropy(model(inputs), targets)
    count = mask.sum()
    return (losses * mask).astype(mx.float32).sum() / count, count
