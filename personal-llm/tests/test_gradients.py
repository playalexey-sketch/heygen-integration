"""Численная проверка backward (finite differences) для всей модели."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from personal_llm.gpt import GPT, GPTConfig, cross_entropy, init_weights  # noqa: E402


def rel_err(a: np.ndarray, b: np.ndarray) -> float:
    """Относительная ошибка с абсолютным допуском для малых градиентов
    (в float32 численная оценка сама шумит на ~1e-3)."""
    a, b = a.astype(np.float64), b.astype(np.float64)
    num = np.abs(a - b)
    den = np.abs(a) + np.abs(b) + 5e-2
    return float((num / den).max())


def main():
    np.random.seed(7)
    cfg = GPTConfig(vocab_size=17, block_size=8, n_layer=2, n_head=2, n_embd=8)
    # случайные веса (не «мягкие» 0.02) — чтобы градиенты были разными
    rng = np.random.default_rng(3)
    w = {k: (rng.normal(0, 0.6, a.shape) * (1.0 if a.ndim == 1 else 1.0)).astype(np.float32)
         for k, a in init_weights(cfg, 1).items()}
    # LayerNorm веса держим близкими к 1, чтобы не убивать динамику
    for k in list(w):
        if k.endswith(".w") and ("ln" in k or k == "lnf.w"):
            w[k] = (1.0 + 0.3 * rng.normal(0, 1, w[k].shape)).astype(np.float32)
    model = GPT(cfg, w)

    x = rng.integers(0, cfg.vocab_size, (2, 8))
    y = rng.integers(0, cfg.vocab_size, (2, 8))
    model.train_step(x, y)
    grads = {k: v.astype(np.float64) for k, v in model.grads.items()}

    # перебираем случайные срезы каждого тензора
    rng2 = np.random.default_rng(11)
    eps = 1e-3  # float32: меньший eps даёт шум округления в численной оценке
    worst = 0.0
    checks = 0
    for name, arr in w.items():
        flat = arr.reshape(-1)
        for _ in range(6):
            idx = int(rng2.integers(0, flat.size))
            old = arr.reshape(-1)[idx]
            arr.reshape(-1)[idx] = old + eps
            l1 = cross_entropy(model._forward_train(x), y)
            arr.reshape(-1)[idx] = old - eps
            l2 = cross_entropy(model._forward_train(x), y)
            num = (l1 - l2) / (2 * eps)
            worst = max(worst, rel_err(np.array([num]), np.array([grads[name].reshape(-1)[idx]])))
            checks += 1
    print(f"проверено срезов: {checks}, max относ. ошибка: {worst:.3e}")
    assert worst < 5e-2, f"backward сломан (ошибка {worst:.3e})"
    print("OK: backward сходится с численным градиентом")


if __name__ == "__main__":
    main()
