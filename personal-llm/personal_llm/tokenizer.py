"""
Токенайзеры для личного LLM.

  * ByteTokenizer  — 256 «слов» (байты UTF-8). Работает без обучения,
                     на любом языке, но токенов больше.
  * BPETokenizer   — обычный BPE (алгоритм из open-source реализации
                     Ken Shen / GPT-2), обучающийся прямо на ВАШЕМ тексте.
  * GPT2Tokenizer  — BPE оригинального GPT-2 (для загрузок открытых весов).

Формат сохранения — pickle (.pkl), читается стандартным Python.
"""
from __future__ import annotations

import pickle
import re
from collections import Counter
from pathlib import Path

WORD_RE = re.compile(r"\s+|\S+")


def _split_words(text: str) -> list[str]:
    return WORD_RE.findall(text)


class ByteTokenizer:
    """Один токен = один байт UTF-8. vocab_size = 256."""

    name = "bytes"
    vocab_size = 256

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def decode(self, ids) -> str:
        return bytes(int(i) for i in ids).decode("utf-8", errors="replace")

    def save(self, path) -> None:
        Path(path).write_bytes(b"")  # маркер «байтовый токенайзер»

    @staticmethod
    def load(path):
        return ByteTokenizer()


class BPETokenizer:
    """BPE, обученный на собственном тексте пользователя."""

    name = "bpe"

    def __init__(self, vocab_bytes: list[bytes], merge_rank: dict[tuple[int, int], int]):
        self.vocab = list(vocab_bytes)          # id -> bytes
        self.merge_rank = merge_rank            # (a,b) -> порядок слияния
        self.vocab_size = len(self.vocab)

    # ---- обучение ----

    @classmethod
    def train(cls, text: str, vocab_size: int = 512, min_freq: int = 3):
        words = [w.encode("utf-8") for w in _split_words(text)]
        cur = [list(w) for w in words]
        vocab = [bytes([i]) for i in range(256)]
        rank: dict[tuple[int, int], int] = {}

        while len(vocab) < vocab_size:
            pairs: Counter = Counter()
            for w in cur:
                for a, b in zip(w, w[1:]):
                    pairs[(a, b)] += 1
            if not pairs:
                break
            best = max(pairs.items(), key=lambda kv: (kv[1], -kv[0][0], -kv[0][1]))
            (pa, pb), cnt = best
            if cnt < min_freq:
                break
            r = len(rank)
            new_id = 256 + r
            rank[(pa, pb)] = r
            vocab.append(vocab[pa] + vocab[pb])
            nxt = []
            for w in cur:
                out, i = [], 0
                while i < len(w):
                    if i < len(w) - 1 and rank.get((w[i], w[i + 1])) == r:
                        out.append(new_id)
                        i += 2
                    else:
                        out.append(w[i])
                        i += 1
                nxt.append(out)
            cur = nxt
        return cls(vocab, rank)

    # ---- кодирование / декодирование ----

    def encode(self, text: str) -> list[int]:
        out: list[int] = []
        for word in _split_words(text):
            cur = list(word.encode("utf-8"))
            while True:
                best_r, best_j = None, -1
                for j in range(len(cur) - 1):
                    r = self.merge_rank.get((cur[j], cur[j + 1]))
                    if r is not None and (best_r is None or r < best_r):
                        best_r, best_j = r, j
                if best_j < 0:
                    break
                cur = cur[:best_j] + [256 + best_r] + cur[best_j + 1:]
            out.extend(cur)
        return out

    def decode(self, ids) -> str:
        return b"".join(self.vocab[int(i)] for i in ids).decode("utf-8", errors="replace")

    def save(self, path) -> None:
        with open(path, "wb") as f:
            pickle.dump({"vocab": self.vocab, "rank": self.merge_rank}, f)

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            d = pickle.load(f)
        return cls(d["vocab"], d["rank"])


class GPT2Tokenizer:
    """BPE оригинального GPT-2 (vocab.json + merges.txt, лицензия MIT)."""

    name = "gpt2"
    vocab_size = 50257

    _PRE_RE = re.compile(
        r"'s|'t|'re|'ve|'m|'ll|'d| ?\w+| ?\d+| ?[^\s\w\d]+|\s+",
        re.UNICODE,
    )

    def __init__(self, encoder: dict[str, int], merges: list[tuple[str, str]]):
        self.encoder = encoder
        self.decoder = {v: k for k, v in encoder.items()}
        self.rank = {(a, b): i for i, (a, b) in enumerate(merges)}
        self.byte2char = {i: chr(i) for i in range(256)}
        self.vocab = [self.decoder[i].encode("utf-8") for i in range(len(self.decoder))]
        self.vocab_size = len(self.decoder)

    @classmethod
    def from_files(cls, vocab_json: str, merges_txt: str):
        import json
        encoder = json.loads(Path(vocab_json).read_text())
        merges = [
            tuple(line.strip().split(" "))
            for line in Path(merges_txt).read_text().splitlines()[1:]
            if line.strip()
        ]
        return cls(encoder, merges)

    def _bpe(self, token: str) -> list[int]:
        word = list(token)
        if len(word) == 1:
            return [self.encoder[token]]
        while True:
            pairs = list(zip(word, word[1:]))
            ranked = [(self.rank[p], j) for j, p in enumerate(pairs) if p in self.rank]
            if not ranked:
                break
            r, j = min(ranked)
            new = self.encoder.get(word[j] + word[j + 1])
            if new is None:
                break
            word = word[:j] + [word[j] + word[j + 1]] + word[j + 2:]
        return [self.encoder[w] for w in word]

    def encode(self, text: str) -> list[int]:
        s = "".join(self.byte2char[c] for c in text.encode("utf-8"))
        out: list[int] = []
        for m in self._PRE_RE.finditer(s):
            out.extend(self._bpe(m.group()))
        return out

    def decode(self, ids) -> str:
        return "".join(self.decoder[int(i)] for i in ids).encode("latin-1", errors="replace").decode("utf-8", errors="replace")

    def save(self, path) -> None:
        with open(path, "wb") as f:
            pickle.dump({"encoder": self.encoder, "rank": self.rank}, f)

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            d = pickle.load(f)
        return cls(d["encoder"], list(d["rank"].keys()))


def load_tokenizer(model_dir) -> object:
    """Читает токенайзер из каталога модели (см. meta['tokenizer'])."""
    model_dir = Path(model_dir)
    tfile = model_dir / "tokenizer.pkl"
    meta = (model_dir / "meta.json")
    import json
    tok_name = json.loads(meta.read_text())["tokenizer"]
    if tok_name == "bytes":
        return ByteTokenizer()
    if tok_name == "bpe":
        return BPETokenizer.load(tfile)
    if tok_name == "gpt2":
        return GPT2Tokenizer.load(tfile)
    raise ValueError(f"неизвестный токенайзер: {tok_name}")
