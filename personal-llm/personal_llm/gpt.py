"""
GPT — маленький декодерный Transformer на чистом NumPy.

Архитектура по открытым источникам (обе лицензии MIT):
  * nanoGPT (Andrej Karpathy)  — https://github.com/karpathy/nanoGPT
  * GPT-2 (OpenAI)             — https://github.com/openai/gpt-2

Здесь реализованы:
  * forward для обучения (с сохранением активаций) и backward «вручную»;
  * быстрый инференс по одному токену через KV-кэш;
  * приём весов через функцию get(name) — так одна и та же модель может
    читать веса из RAM, из LRU-кэша с выгрузкой на диск и т.п.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EPS = 1e-5
_GELU_B = np.float32(0.7978845608028654)


@dataclass
class GPTConfig:
    vocab_size: int
    block_size: int   # максимальная длина последовательности
    n_layer: int
    n_head: int
    n_embd: int

    @property
    def head_dim(self) -> int:
        return self.n_embd // self.n_head

    def weight_names(self) -> list[str]:
        names = ["wte", "wpe"]
        for i in range(self.n_layer):
            names += [
                f"ln1_{i}.w", f"ln1_{i}.b",
                f"attn_{i}.wqkv", f"attn_{i}.bqkv", f"attn_{i}.wo",
                f"ln2_{i}.w", f"ln2_{i}.b",
                f"mlp_{i}.w1", f"mlp_{i}.b1", f"mlp_{i}.w2", f"mlp_{i}.b2",
            ]
        names += ["lnf.w", "lnf.b"]
        return names

    def n_params(self) -> int:
        V, T, L, C = self.vocab_size, self.block_size, self.n_layer, self.n_embd
        p = V * C + T * C
        for _ in range(L):
            p += 2 * C            # ln1
            p += C * 3 * C + 3 * C + C * C   # attn (qkv + bias + out)
            p += 2 * C            # ln2
            p += C * 4 * C + 4 * C + 4 * C * C + 4 * C  # mlp
        p += 2 * C                # lnf
        return p


def init_weights(cfg: GPTConfig, seed: int = 1337) -> dict[str, np.ndarray]:
    """Инициализация, как в GPT-2: N(0, 0.02), LayerNorm = 1/0."""
    rng = np.random.default_rng(seed)
    C, V, T, L = cfg.n_embd, cfg.vocab_size, cfg.block_size, cfg.n_layer

    def mat(a, b=None):
        shape = (a, b) if b is not None else (a,)
        return rng.normal(0.0, 0.02, shape).astype(np.float32)

    w: dict[str, np.ndarray] = {
        "wte": mat(V, C),
        "wpe": mat(T, C),
    }
    for i in range(L):
        w[f"ln1_{i}.w"] = np.ones(C, np.float32)
        w[f"ln1_{i}.b"] = np.zeros(C, np.float32)
        w[f"attn_{i}.wqkv"] = mat(C, 3 * C)
        w[f"attn_{i}.bqkv"] = np.zeros(3 * C, np.float32)
        w[f"attn_{i}.wo"] = mat(C, C)
        w[f"ln2_{i}.w"] = np.ones(C, np.float32)
        w[f"ln2_{i}.b"] = np.zeros(C, np.float32)
        w[f"mlp_{i}.w1"] = mat(C, 4 * C)
        w[f"mlp_{i}.b1"] = np.zeros(4 * C, np.float32)
        w[f"mlp_{i}.w2"] = mat(4 * C, C)
        w[f"mlp_{i}.b2"] = np.zeros(C, np.float32)
    w["lnf.w"] = np.ones(C, np.float32)
    w["lnf.b"] = np.zeros(C, np.float32)
    return w


# --------------------------------------------------------------------------
# Базовые блоки
# --------------------------------------------------------------------------

def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


def gelu(x: np.ndarray) -> np.ndarray:
    """GELU, tanh-приближение (как в GPT-2)."""
    t = np.tanh(_GELU_B * (x + 0.044715 * x**3))
    return (0.5 * x * (1.0 + t)).astype(np.float32)


def gelu_backward(x: np.ndarray, dx: np.ndarray) -> np.ndarray:
    t = np.tanh(_GELU_B * (x + 0.044715 * x**3))
    d = 0.5 * (1.0 + t) + 0.5 * x * (1.0 - t**2) * _GELU_B * (1.0 + 3.0 * 0.044715 * x**2)
    return (dx * d).astype(np.float32)


def ln_forward(x, w, b):
    """LayerNorm. Возвращает (y, x_hat, inv_std)."""
    mean = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    inv = 1.0 / np.sqrt(var + EPS)
    xh = (x - mean) * inv
    return (xh * w + b).astype(np.float32), xh, inv


def ln_backward(xh, inv, w, dx):
    """Обратное для LayerNorm. xh — нормализованный вход, inv — 1/std."""
    dxb = dx * w
    dxh = (dxb - dxb.mean(axis=-1, keepdims=True)
           - xh * (dxb * xh).mean(axis=-1, keepdims=True))
    dout = (dxh * inv).astype(np.float32)
    axes = tuple(range(dx.ndim - 1))
    dw = (xh * dx).sum(axis=axes)
    db = dx.sum(axis=axes)
    return dout.astype(np.float32), dw, db


# --------------------------------------------------------------------------
# Внимательность
# --------------------------------------------------------------------------

def _attn_prefix(h1, i, get, cfg):
    """Полное (causal) внимание по всему префиксу. h1: (B, T, C).
    Возвращает (O, P, q, k, v) — O: (B,T,C), P: (B,T,H,T)."""
    C, H, HD = cfg.n_embd, cfg.n_head, cfg.head_dim
    B, T = h1.shape[:2]
    wqkv, bqkv, wo = get(f"attn_{i}.wqkv"), get(f"attn_{i}.bqkv"), get(f"attn_{i}.wo")

    qkv = (h1 @ wqkv + bqkv).astype(np.float32)          # (B,T,3C)
    q, k, v = qkv[..., :C], qkv[..., C:2 * C], qkv[..., 2 * C:]
    qh = q.reshape(B, T, H, HD)
    kh = k.reshape(B, T, H, HD)
    vh = v.reshape(B, T, H, HD)

    S = (np.einsum("btgd,bjgd->btgj", qh, kh) / math.sqrt(HD)).astype(np.float32)
    mask = np.triu(np.ones((T, T), np.bool_), k=1).reshape(1, T, 1, T)
    S = np.where(mask, S - 1e9, S)
    P = softmax(S, axis=-1)
    A = np.einsum("btgj,bjgd->btgd", P, vh).reshape(B, T, C)
    O = (A @ wo).astype(np.float32)
    return O, P, q, k, v, A


class KVCache:
    """Препрейаллоцированный KV-кэш на инференс (в RAM, небольшой)."""

    def __init__(self, cfg: GPTConfig):
        self.n_layer = cfg.n_layer
        self.C = cfg.n_embd
        self.max_t = cfg.block_size
        self.k = [np.zeros((self.max_t, self.C), np.float32) for _ in range(cfg.n_layer)]
        self.v = [np.zeros((self.max_t, self.C), np.float32) for _ in range(cfg.n_layer)]
        self.t = 0

    def set(self, i, k: np.ndarray, v: np.ndarray):
        """Пишет k,v слоя i на текущей позиции (без сдвига позиции)."""
        self.k[i][self.t] = k
        self.v[i][self.t] = v

    def step(self):
        """Один токен вперёд — вызывает forward_token после всех слоёв."""
        if self.t >= self.max_t:
            raise RuntimeError("KV-кэш переполнен (достигнут block_size)")
        self.t += 1


def _attn_token(h1, i, kv: KVCache, get, cfg):
    """Внимание для одного нового токена. h1: (C,).
    Возвращает (O: (C,), k: (C,), v: (C,)) и дописывает k,v в кэш."""
    C, H, HD = cfg.n_embd, cfg.n_head, cfg.head_dim
    wqkv, bqkv, wo = get(f"attn_{i}.wqkv"), get(f"attn_{i}.bqkv"), get(f"attn_{i}.wo")

    q = h1 @ wqkv[:, :C] + bqkv[:C]
    k = h1 @ wqkv[:, C:2 * C] + bqkv[C:2 * C]
    v = h1 @ wqkv[:, 2 * C:] + bqkv[2 * C:]

    qh = q.reshape(H, HD)
    kv.set(i, k, v)                     # текущий k,v — на позиции kv.t
    t = kv.t + 1                        # внимания: прошлые + текущий
    kh = kv.k[i][:t].reshape(t, H, HD)
    vh = kv.v[i][:t].reshape(t, H, HD)

    # S: (t, H)  — S[j, h] = k_j · q_h
    S = (np.einsum("jhd,hd->jh", kh, qh) / math.sqrt(HD)).astype(np.float32)
    P = softmax(S, axis=0)                                 # softmax по времени (j)
    A = np.einsum("jh,jhd->hd", P, vh).reshape(C)          # (C,)
    O = (A @ wo).astype(np.float32)
    return O, k, v


# --------------------------------------------------------------------------
# Модель
# --------------------------------------------------------------------------

class GPT:
    """GPT с ручным backward.

    weights  — dict name -> ndarray (для обучения);
    weight_getter — опциональная функция name -> ndarray (для инференса
    через кэш с выгрузкой на диск).
    """

    def __init__(self, cfg: GPTConfig, weights: dict[str, np.ndarray] | None = None,
                 weight_getter=None):
        self.cfg = cfg
        self.w = weights if weights is not None else {}
        self._get = weight_getter
        self.grads: dict[str, np.ndarray] = {}
        self._ctx = None

    def get(self, name: str) -> np.ndarray:
        if self._get is not None:
            return self._get(name)
        return self.w[name]

    # ---------------- обучение ----------------

    def train_step(self, x: np.ndarray, y: np.ndarray) -> float:
        """x, y: (B, T) int. Возвращает loss; градиенты — в self.grads."""
        logits = self._forward_train(x)
        loss = cross_entropy(logits, y)
        self._backward(logits, y)
        return float(loss)

    def _forward_train(self, x):
        cfg = self.cfg
        B, T = x.shape
        wte, wpe = self.w["wte"], self.w["wpe"]
        emb = (wte[x] + wpe[:T]).astype(np.float32)        # (B,T,C)

        layers = []
        h = emb
        for i in range(cfg.n_layer):
            h_in = h
            h1, xh1, inv1 = ln_forward(h, self.w[f"ln1_{i}.w"], self.w[f"ln1_{i}.b"])
            O, P, q, k, v, A = _attn_prefix(h1, i, self.w.__getitem__, cfg)
            h2res = h_in + O
            h2, xh2, inv2 = ln_forward(h2res, self.w[f"ln2_{i}.w"], self.w[f"ln2_{i}.b"])
            w1x = (h2 @ self.w[f"mlp_{i}.w1"] + self.w[f"mlp_{i}.b1"]).astype(np.float32)
            u = gelu(w1x)
            h = (h2res + u @ self.w[f"mlp_{i}.w2"] + self.w[f"mlp_{i}.b2"]).astype(np.float32)
            layers.append(dict(h_in=h_in, h1=h1, xh1=xh1, inv1=inv1,
                               P=P, q=q, k=k, v=v, O=O, A=A,
                               h2res=h2res, h2=h2, xh2=xh2, inv2=inv2,
                               w1x=w1x, u=u))

        z, xhf, invf = ln_forward(h, self.w["lnf.w"], self.w["lnf.b"])
        logits = (z @ wte.T).astype(np.float32)
        self._ctx = dict(x=x, emb=emb, layers=layers, z=z, xhf=xhf, invf=invf)
        return logits

    def _backward(self, logits, y):
        ctx = self._ctx
        cfg = self.cfg
        C = cfg.n_embd
        x = ctx["x"]
        B, T = x.shape
        wte = self.w["wte"]

        probs = softmax(logits, axis=-1)
        dlogits = probs
        b_idx = np.repeat(np.arange(B), T)
        t_idx = np.tile(np.arange(T), B)
        np.subtract.at(dlogits, (b_idx, t_idx, y.reshape(-1)), 1.0)
        dlogits /= B * T

        z = ctx["z"]
        grads: dict[str, np.ndarray] = {}
        dwte = np.einsum("btd,btv->vd", z, dlogits).astype(np.float32)  # lm_head = wte
        dz = (dlogits @ wte).astype(np.float32)
        dh, dwf, dbf = ln_backward(ctx["xhf"], ctx["invf"], self.w["lnf.w"], dz)
        grads["lnf.w"], grads["lnf.b"] = dwf, dbf

        for i in reversed(range(cfg.n_layer)):
            lc = ctx["layers"][i]
            # --- MLP ---
            u, w1x, h2 = lc["u"], lc["w1x"], lc["h2"]
            w1 = self.w[f"mlp_{i}.w1"]
            w2 = self.w[f"mlp_{i}.w2"]
            do2 = dh                                   # h_out = h2res + o2
            grads[f"mlp_{i}.w2"] = np.einsum("btm,btn->mn", u, do2).astype(np.float32)
            grads[f"mlp_{i}.b2"] = do2.sum(axis=(0, 1))
            du = do2 @ w2.T
            dw1x = gelu_backward(w1x, du)
            grads[f"mlp_{i}.w1"] = np.einsum("btd,btm->dm", h2, dw1x).astype(np.float32)
            grads[f"mlp_{i}.b1"] = dw1x.sum(axis=(0, 1))
            dh2 = dw1x @ w1.T
            # --- LayerNorm 2 + остаточное ---
            # h2res = h_in + O, h = h2res + o2: к h2res приходят ДВЕ ветки —
            # прямое остаточное (dh) и через mlp/ln2 (d_mlp).
            d_mlp, dw2n, db2n = ln_backward(lc["xh2"], lc["inv2"],
                                            self.w[f"ln2_{i}.w"], dh2)
            grads[f"ln2_{i}.w"], grads[f"ln2_{i}.b"] = dw2n, db2n
            d_h2res = dh + d_mlp                       # полный градиент по h2res
            # --- внимание ---
            dO = d_h2res                               # h2res = h_in + O
            O, P, q, k, v = lc["O"], lc["P"], lc["q"], lc["k"], lc["v"]
            A = lc["A"]
            wo = self.w[f"attn_{i}.wo"]
            grads[f"attn_{i}.wo"] = np.einsum("btd,bte->de", A, dO).astype(np.float32)
            dA = dO @ wo.T
            H, HD = cfg.n_head, cfg.head_dim
            dA4 = dA.reshape(B, T, H, HD)
            q4, k4, v4 = (a.reshape(B, T, H, HD) for a in (q, k, v))
            dP = np.einsum("btgd,bjgd->btgj", dA4, v4)
            dS = (P * (dP - (dP * P).sum(axis=-1, keepdims=True))
                  / math.sqrt(HD)).astype(np.float32)
            dq = np.einsum("btgj,bjgd->btgd", dS, k4).reshape(B, T, C)
            dk = np.einsum("btgj,btgd->bjgd", dS, q4).reshape(B, T, C)
            dv = np.einsum("btgj,btgd->bjgd", P, dA4).reshape(B, T, C)
            # порядок строго [Q | K | V] — как в forward (qkv = h1 @ wqkv)
            dQKV = np.concatenate([dq, dk, dv], axis=-1)
            h1 = lc["h1"]
            wqkv = self.w[f"attn_{i}.wqkv"]
            grads[f"attn_{i}.wqkv"] = np.einsum("btd,btj->dj", h1, dQKV).astype(np.float32)
            grads[f"attn_{i}.bqkv"] = dQKV.sum(axis=(0, 1))
            dh1 = dQKV @ wqkv.T
            # --- LayerNorm 1 + остаточное ---
            dh_in, dw1n, db1n = ln_backward(lc["xh1"], lc["inv1"],
                                            self.w[f"ln1_{i}.w"], dh1)
            grads[f"ln1_{i}.w"], grads[f"ln1_{i}.b"] = dw1n, db1n
            dh = d_h2res + dh_in                       # dL/dh_in

        # --- эмбеддинги ---
        d_wte = dwte.copy()
        for b in range(B):
            np.add.at(d_wte, x[b], dh[b])
        grads["wte"] = d_wte.astype(np.float32)
        grads["wpe"] = np.zeros_like(self.w["wpe"])
        grads["wpe"][:T] = dh.sum(axis=0)

        self.grads = grads

    # ---------------- инференс ----------------

    def forward_prefix(self, ids, kv: KVCache):
        """Прогоняет префикс (до block_size токенов), заполняет KV-кэш,
        возвращает скрытое состояние последней позиции: (C,)."""
        cfg = self.cfg
        x = np.array(ids[-cfg.block_size:], np.int64)[None, :]
        B, T = x.shape
        wte = self.get("wte")
        wpe = self.get("wpe")
        h = (wte[x] + wpe[:T]).astype(np.float32)[0]     # (T, C)

        for i in range(cfg.n_layer):
            h1, _, _ = ln_forward(h[None], self.get(f"ln1_{i}.w"), self.get(f"ln1_{i}.b"))
            O, P, qf, kf, vf, Af = _attn_prefix(h1, i, self.get, cfg)
            # сохраняем K,V в кэш
            kv.k[i][:T] = kf[0]
            kv.v[i][:T] = vf[0]
            h = h + O[0]
            h2, _, _ = ln_forward(h[None], self.get(f"ln2_{i}.w"), self.get(f"ln2_{i}.b"))
            u = gelu(h2[0] @ self.get(f"mlp_{i}.w1") + self.get(f"mlp_{i}.b1"))
            h = h + u @ self.get(f"mlp_{i}.w2") + self.get(f"mlp_{i}.b2")
        kv.t = T
        return h[-1]

    def forward_token(self, h: np.ndarray, kv: KVCache):
        """Один токен. h: (C,) — скрытое состояние перед слоем 0.
        Возвращает (h_next: (C,), logits: (V,))."""
        cfg = self.cfg
        for i in range(cfg.n_layer):
            h1, _, _ = ln_forward(h[None], self.get(f"ln1_{i}.w"), self.get(f"ln1_{i}.b"))
            O, _, _ = _attn_token(h1[0], i, kv, self.get, cfg)
            h = h + O
            h2, _, _ = ln_forward(h[None], self.get(f"ln2_{i}.w"), self.get(f"ln2_{i}.b"))
            u = gelu(h2[0] @ self.get(f"mlp_{i}.w1") + self.get(f"mlp_{i}.b1"))
            h = h + u @ self.get(f"mlp_{i}.w2") + self.get(f"mlp_{i}.b2")
        kv.step()                                    # один токен = один сдвиг позиции
        logits = self.logits_from_hidden(h)
        return h, logits

    def logits_from_hidden(self, h: np.ndarray) -> np.ndarray:
        """logits (V,) по скрытому состоянию последней позиции."""
        z, _, _ = ln_forward(h[None], self.get("lnf.w"), self.get("lnf.b"))
        return (z[0] @ self.get("wte").T).astype(np.float32)

    def embed(self, token_id: int, pos: int) -> np.ndarray:
        return (self.get("wte")[token_id] + self.get("wpe")[pos]).astype(np.float32)


def cross_entropy(logits, y) -> float:
    """Метрический cross-entropy (как в nanoGPT)."""
    m = logits.max(axis=-1, keepdims=True)
    logp = logits - m - np.log(np.exp(logits - m).sum(axis=-1, keepdims=True))
    b_idx = np.repeat(np.arange(y.shape[0]), y.shape[1])
    t_idx = np.tile(np.arange(y.shape[1]), y.shape[0])
    return float(-logp[b_idx, t_idx, y.reshape(-1)].mean())


def sample_token(logits: np.ndarray, temperature: float = 0.8,
                 top_k: int = 40, rng: np.random.Generator | None = None) -> int:
    rng = rng or np.random.default_rng()
    z = logits / max(temperature, 1e-6)
    if top_k and top_k < z.size:
        thr = np.partition(z, -top_k)[-top_k]
        z = np.where(z < thr, -1e9, z)
    p = softmax(z)
    return int(rng.choice(p.size, p=p))
