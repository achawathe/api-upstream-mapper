"""Small executable regression check for response masking, using the installed MLX runtime."""

from experiments.local_reranker.runtime import offline


def main():
    offline()
    import mlx.core as mx

    from experiments.local_reranker.loss import answer_loss

    batch = mx.array([[1, 2, 3, 4, 0, 0]])
    bounds = mx.array([[2, 4]])
    logits = mx.zeros((1, 5, 5))
    value, count = answer_loss(lambda _: logits, batch, bounds)
    assert count.item() == 2
    assert abs(value.item() - 1.6094379) < 1e-5
    altered = logits.at[0, 3:, 0].add(100)
    other, other_count = answer_loss(lambda _: altered, batch, bounds)
    assert other_count.item() == 2 and abs(value.item() - other.item()) < 1e-6
    print("LOSS_MASK_CHECK_PASSED")


if __name__ == "__main__":
    main()
