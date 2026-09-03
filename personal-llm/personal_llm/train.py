"""
Обучение личного LLM на ВАШЕМ тексте (заметки, заметки, переписка,
статьи — что угодно). Всё работает на CPU, только numpy.

Пресеты (размер модели / время обучения на ноутбуке):
  micro  ~3M параметров   — несколько минут
  small  ~14M параметров  — ~15-30 минут
"""
from __future__ import annotations

import time

import numpy as np

from .diskstore import ModelLib
from .gpt import GPT, GPTConfig, init_weights
from .tokenizer import BPETokenizer, ByteTokenizer

PRESETS = {
    "micro": dict(n_layer=6, n_head=6, n_embd=192, block_size=96),
    "small": dict(n_layer=8, n_head=8, n_embd=384, block_size=128),
}


def _adam_step(w, grads, m, v, t, lr, b1=0.9, b2=0.95, eps=1e-8):
    for name, g in grads.items():
        mm = m[name]
        mm *= b1
        mm += (1 - b1) * g
        vv = v[name]
        vv *= b2
        vv += (1 - b2) * (g * g)
        mh = mm / (1 - b1**t)
        vh = vv / (1 - b2**t)
        w[name] = w[name] - lr * mh / (np.sqrt(vh) + eps)


def clip_grads(w, grads, max_norm=1.0):
    total = 0.0
    for g in grads.values():
        total += float((g.astype(np.float64) ** 2).sum())
    total = total ** 0.5
    if total > max_norm:
        s = max_norm / (total + 1e-12)
        for g in grads.values():
            g *= s
    return total


def train(texts: list[str], name: str, lib: ModelLib,
          preset: str = "micro", vocab_size: int = 512,
          tokens: int = 60_000, batch: int = 16, lr: float = 3e-4,
          seed: int = 1337, quantize: bool = False,
          log_every: int = 200, use_bpe: bool = True) -> dict:
    """Обучает модель и сохраняет её в библиотеку. Возвращает статистику."""
    text = "\n".join(texts)
    if len(text) < 400:
        raise ValueError("Слишком мало текста (нужно хотя бы ~1KB). "
                         "Скиньте больше файлов в --data.")

    t0 = time.time()
    if use_bpe:
        tok = BPETokenizer.train(text, vocab_size=vocab_size)
    else:
        tok = ByteTokenizer()
    ids = np.array(tok.encode(text), dtype=np.int32)
    n = len(ids)
    print(f"[train] текста: {len(text):,} символов, токенов: {n:,}, "
          f"vocab: {tok.vocab_size}")

    p = PRESETS[preset]
    cfg = GPTConfig(vocab_size=tok.vocab_size, block_size=p["block_size"],
                    n_layer=p["n_layer"], n_head=p["n_head"],
                    n_embd=p["n_embd"])
    print(f"[train] модель {preset}: {cfg.n_layer} слоёв, {cfg.n_embd} embd, "
          f"~{cfg.n_params() / 1e6:.1f}M параметров, "
          f"~{cfg.n_params() * 4 / 2**20:.0f} МБ на диске")

    w = init_weights(cfg, seed)
    model = GPT(cfg, w)
    m = {k: np.zeros_like(a) for k, a in w.items()}
    v = {k: np.zeros_like(a) for k, a in w.items()}
    rng = np.random.default_rng(seed)

    seen = 0
    it = 0
    last_loss = None
    while seen < tokens:
        B = min(batch, max(1, (tokens - seen) // p["block_size"]))
        off = rng.integers(0, n - p["block_size"], size=B)
        x = np.stack([ids[o:o + p["block_size"]] for o in off])
        y = np.stack([ids[o + 1:o + 1 + p["block_size"]] for o in off])

        loss = model.train_step(x, y)
        grad_norm = clip_grads(w, model.grads)
        it += 1
        _adam_step(w, model.grads, m, v, it, lr)
        seen += B * p["block_size"]
        last_loss = loss

        if it % log_every == 0:
            dt = time.time() - t0
            tps = seen / max(dt, 1e-9)
            eta = (tokens - seen) / max(tps, 1)
            print(f"[train] шаг {it:>6} | loss {loss:.3f} | "
                  f"{seen:,}/{tokens:,} токенов | {tps:,.0f} ток/с | "
                  f"осталось ~{eta:.0f} с", flush=True)

    # маленькая проверка: loss не взорвалась
    off = rng.integers(0, n - p["block_size"], size=min(batch, 8))
    x = np.stack([ids[o:o + p["block_size"]] for o in off])
    y = np.stack([ids[o + 1:o + 1 + p["block_size"]] for o in off])
    from .gpt import cross_entropy
    final_loss = cross_entropy(model._forward_train(x), y)

    meta = dict(
        name=name, preset=preset, seed=seed,
        config=cfg.__dict__,
        params=cfg.n_params(),
        train_tokens=seen, train_seconds=int(time.time() - t0),
        final_loss=round(final_loss, 4),
        text_chars=len(text),
        created=time.strftime("%Y-%m-%d %H:%M"),
        source="personal",
    )
    lib.save(name, w, meta, tok, quantize=quantize)
    d = lib.models_dir / name
    disk_mb = (d / "weights.bin").stat().st_size / 2**20
    print(f"[train] готово: {name}\n"
          f"          loss {last_loss:.3f} -> {final_loss:.3f} | "
          f"{time.time() - t0:.0f} с\n"
          f"          файл: {d / 'weights.bin'} ({disk_mb:.1f} МБ на диске)")
    return meta
