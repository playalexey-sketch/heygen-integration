"""
Дисковый хранилище весов + LRU-кэш в RAM.

Это и есть принцип «подгружаем только то, что нужно»:

  * ВСЕ веса модели лежат на диске в одном бинарном файле weights.bin
    (иногда со сжатием до int8 — в 4 раза меньше).
  * В оперативную память подгружается ТОЛЬКО текущий слой/матрица,
    и то только если RAM-бюджет (--ram-mb) позволяет.
  * ЛRU-кэш держит самые свежие тензоры; вытесненные — просто
    «выпадают» из RAM и остаются на диске, откуда читаются заново
    при следующем обращении.

Формат weights.bin (little-endian):
  MAGIC 'PLW1'
  u32  количество тензоров
  u32  длина meta + json(meta)
  для каждого тензора:
    u32  len(name) | name
    u32  ndim      | i64 dims...
    u8   flags (bit0 = int8-квантование)
    f32  scale
    u64  nbytes
    данные
"""
from __future__ import annotations

import json
import struct
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAGIC = b"PLW1"


# --------------------------------------------------------------------------
# Хранилище на диске
# --------------------------------------------------------------------------

@dataclass
class _Entry:
    offset: int
    nbytes: int
    quant: bool
    scale: float
    shape: tuple


class WeightStore:
    """Бинарный файл с тензорами. Источник правды всегда — диск."""

    def __init__(self, path):
        self.path = Path(path)
        self._index: dict[str, _Entry] | None = None
        self.meta: dict = {}

    # ---- создание ----

    @classmethod
    def create(cls, path, weights: dict[str, np.ndarray], meta: dict,
               quantize: bool = False) -> "WeightStore":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(MAGIC)
            f.write(struct.pack("<I", len(weights)))
            meta_b = json.dumps(meta, ensure_ascii=False).encode()
            f.write(struct.pack("<I", len(meta_b)))
            f.write(meta_b)
            for name, arr in weights.items():
                arr = np.ascontiguousarray(arr)
                nb = name.encode()
                if quantize and arr.dtype in (np.float32,) and arr.size:
                    mx = float(np.abs(arr).max())
                    scale = (mx / 127.0) if mx > 0 else 1.0
                    q = np.round(arr / scale).clip(-127, 127).astype(np.int8)
                    data, flags = q.tobytes(), 1
                else:
                    data, flags, scale = arr.astype(np.float32).tobytes(), 0, 1.0
                f.write(struct.pack("<I", len(nb)))
                f.write(nb)
                shape = arr.shape
                f.write(struct.pack("<I", len(shape)))
                f.write(struct.pack(f"<{len(shape)}q", *shape))
                f.write(struct.pack("<B", flags))
                f.write(struct.pack("<f", scale))
                f.write(struct.pack("<Q", len(data)))
                f.write(data)
        return cls(path)

    # ---- чтение ----

    def _load_index(self):
        if self._index is not None:
            return
        index: dict[str, _Entry] = {}
        with open(self.path, "rb") as f:
            if f.read(4) != MAGIC:
                raise ValueError(f"{self.path}: не файл весов personal-llm")
            (n,) = struct.unpack("<I", f.read(4))
            (mlen,) = struct.unpack("<I", f.read(4))
            self.meta = json.loads(f.read(mlen))
            for _ in range(n):
                (nlen,) = struct.unpack("<I", f.read(4))
                name = f.read(nlen).decode()
                (ndim,) = struct.unpack("<I", f.read(4))
                shape = tuple(struct.unpack(f"<{ndim}q", f.read(8 * ndim))) if ndim else ()
                (flags,) = struct.unpack("<B", f.read(1))
                (scale,) = struct.unpack("<f", f.read(4))
                (nbytes,) = struct.unpack("<Q", f.read(8))
                offset = f.tell()
                index[name] = _Entry(offset, nbytes, bool(flags & 1), scale, shape)
                f.seek(offset + nbytes)
        self._index = index

    @property
    def tensor_names(self) -> list[str]:
        self._load_index()
        return list(self._index)

    def read(self, name: str) -> np.ndarray:
        self._load_index()
        e = self._index[name]
        with open(self.path, "rb") as f:
            f.seek(e.offset)
            raw = f.read(e.nbytes)
        if e.quant:
            arr = np.frombuffer(raw, dtype=np.int8).astype(np.float32) * e.scale
        else:
            arr = np.frombuffer(raw, dtype=np.float32)
        return arr.reshape(e.shape)

    def disk_size_mb(self) -> float:
        return self.path.stat().st_size / 2**20


# --------------------------------------------------------------------------
# LRU-кэш «RAM <-> диск»
# --------------------------------------------------------------------------

class OffloadCache:
    """Держит в RAM не больше budget_bytes байтов весов.

    * get(name) — возвращает тензор; если его нет в RAM — читает с диска.
    * При превышении бюджета самые старые тензоры вытесняются из RAM
      (на диске они остаются и читаются заново, когда понадобятся).
    """

    def __init__(self, store: WeightStore, budget_bytes: int, verbose: bool = False):
        self.store = store
        self.budget = int(budget_bytes)
        self.verbose = verbose
        self._d: "OrderedDict[str, tuple[int, np.ndarray]]" = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.bytes_loaded = 0

    def _size(self) -> int:
        return sum(n for n, _ in self._d.values())

    def get(self, name: str) -> np.ndarray:
        if name in self._d:
            self._d.move_to_end(name)
            self.hits += 1
            return self._d[name][1]
        arr = self.store.read(name)
        n = arr.nbytes
        self.misses += 1
        self.bytes_loaded += n
        if self.verbose:
            print(f"    [offload] + RAM  {name:<24} {n / 2**20:8.1f} МБ (с диска)",
                  flush=True)
        self._d[name] = (n, arr)
        self._trim()
        return arr

    def _trim(self):
        while self._size() > self.budget and len(self._d) > 1:
            name, (n, _) = self._d.popitem(last=False)
            self.evictions += 1
            if self.verbose:
                print(f"    [offload] - RAM  {name:<24} {n / 2**20:8.1f} МБ "
                      f"(вытеснен, остался на диске)", flush=True)

    @property
    def ram_bytes(self) -> int:
        return self._size()

    def stats_str(self) -> str:
        return (f"кэш: {self.hits} попаданий, {self.misses} промахов, "
                f"{self.evictions} вытеснений, с диска прочитано "
                f"{self.bytes_loaded / 2**20:.0f} МБ, в RAM "
                f"{self.ram_bytes / 2**20:.0f} / {self.budget / 2**20:.0f} МБ")


# --------------------------------------------------------------------------
# Библиотека моделей
# --------------------------------------------------------------------------

class ModelLib:
    """Каталог ~/.cache/personal-llm/models/<имя>/..."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        (self.root / "models").mkdir(parents=True, exist_ok=True)
        (self.root / "presets").mkdir(parents=True, exist_ok=True)

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    def save(self, name, weights, meta: dict, tokenizer, quantize: bool = False) -> Path:
        d = self.models_dir / name
        d.mkdir(parents=True, exist_ok=True)
        meta = dict(meta, tokenizer=tokenizer.name, quantized=bool(quantize))
        WeightStore.create(d / "weights.bin", weights, meta, quantize=quantize)
        tokenizer.save(d / "tokenizer.pkl")
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return d

    def list(self) -> list[str]:
        out = []
        for d in sorted(self.models_dir.iterdir()):
            if (d / "weights.bin").exists():
                out.append(d.name)
        return out

    def latest(self) -> str | None:
        names = self.list()
        if not names:
            return None
        return max((d for d in names), key=lambda n:
                   (self.models_dir / n / "weights.bin").stat().st_mtime)

    def open(self, name) -> tuple["WeightStore", dict, Path]:
        d = self.models_dir / name
        store = WeightStore(d / "weights.bin")
        store._load_index()
        meta = json.loads((d / "meta.json").read_text())
        return store, meta, d
