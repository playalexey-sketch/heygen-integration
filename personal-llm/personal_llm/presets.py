"""
Готовые открытые модели (нужен интернет только на установку).

  gpt2  — GPT-2 124M (OpenAI, лицензия MIT): vocab 50257, 12 слоёв.
          Работает сразу, «знает» английский (и немного других языков).
          После установки весы лежат У ВАС на диске, офлайн.

Читает safetensors (простой открытый формат) и pytorch .bin
(самодостаточный мини-парсер, без зависимости от torch).
"""
from __future__ import annotations

import io
import json
import struct
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from .diskstore import ModelLib
from .gpt import GPTConfig
from .tokenizer import GPT2Tokenizer

HF_BASE = "https://huggingface.co"


def _download(url: str, dest: Path, quiet: bool = False):
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if not quiet:
        print(f"[preset] скачиваю {url} ...")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if not quiet and total:
                print(f"\r[preset]   {done / 2**20:7.1f} / {total / 2**20:.1f} МБ",
                      end="", flush=True)
    if not quiet:
        print()
    tmp.rename(dest)


# --------------------------------------------------------------------------
# Читатели форматов весов
# --------------------------------------------------------------------------

_ST_DTYPES = {"F64": np.float64, "F32": np.float32, "F16": np.float16,
              "BF16": np.uint16, "I64": np.int64, "I32": np.int32,
              "I16": np.int16, "I8": np.int8, "U8": np.uint8,
              "U16": np.uint16, "U32": np.uint32, "U64": np.uint64, "B": np.bool_}


def load_safetensors(path) -> dict[str, np.ndarray]:
    """Самодостаточный читатель формата safetensors (Apache-2.0)."""
    out: dict[str, np.ndarray] = {}
    with open(path, "rb") as f:
        (hlen,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(hlen))
        for name, info in header.items():
            if name == "__metadata__":
                continue
            lo, hi = info["data_offsets"]
            f.seek(lo)
            data = f.read(hi - lo)
            arr = np.frombuffer(data, dtype=_ST_DTYPES[info["dtype"]])
            if info["dtype"] == "BF16":
                arr = _bf16_to_f32(arr)
            arr = arr.reshape(info["shape"]).astype(np.float32, copy=False)
            out[name] = np.ascontiguousarray(arr)
    return out


def _bf16_to_f32(u16: np.ndarray) -> np.ndarray:
    u32 = u16.astype(np.uint32) << 16
    return u32.view(np.float32)


class _TensorStub:
    __slots__ = ("storage", "dtype", "size", "offset", "stride")

    def __init__(self, storage, dtype, size, offset, stride):
        self.storage, self.dtype = storage, dtype
        self.size, self.offset, self.stride = size, offset, stride


class _StorageStub:
    def __init__(self, location=""):
        self.location = location

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.location = state.get("location", self.location)


_TORCH_DTYPE_NAMES = {
    "float32": np.float32, "float64": np.float64, "float16": np.float16,
    "int8": np.int8, "int16": np.int16, "int32": np.int32, "int64": np.int64,
    "uint8": np.uint8, "bool": np.bool_,
}


def load_torch_bin(path) -> dict[str, np.ndarray]:
    """Мини-парсер pytorch-файлов (.bin) без torch.

    Файл — zip: pickle-описание (data.pkl) + сырые блоки (data/0, ...).
    Подменяем pickle-конструкторы torch на свои заглушки и собираем
    state_dict {имя: ndarray}.
    """
    import pickle

    with zipfile.ZipFile(path) as z:
        pkl = z.read("data.pkl")
        blobs = {n: z.read(n) for n in z.namelist() if n.startswith("data/")}

    class _Unpickler(pickle.Unpickler):
        def find_class(self, module, name):
            if module == "torch._utils" and name == "_rebuild_tensor_v2":
                def rebuild_tensor(storage, dtype, size, storage_offset, stride, *rest):
                    return _TensorStub(storage, dtype, tuple(size),
                                       storage_offset, tuple(stride))
                return rebuild_tensor
            if module == "torch._utils" and name in ("_rebuild_storage",
                                                     "_rebuild_parameter"):
                def rebuild_storage(storage_cls, *args):
                    loc = next((a for a in args if isinstance(a, str)), "")
                    return _StorageStub(loc)
                return rebuild_storage
            if module == "torch" and name in _TORCH_DTYPE_NAMES:
                return _TORCH_DTYPE_NAMES[name]
            if module == "torch" and name.endswith("Storage"):
                return _StorageStub
            raise pickle.UnpicklingError(
                f"неожиданный класс в torch pickle: {module}.{name} "
                "(версия torch изменила формат?)")

    state = _Unpickler(io.BytesIO(pkl)).load()
    if not isinstance(state, dict):
        raise RuntimeError("в pytorch-файле не state_dict (dict)")
    out: dict[str, np.ndarray] = {}
    for k, t in state.items():
        if isinstance(t, _TensorStub):
            out[str(k)] = _materialize(t, blobs)
    if not out:
        raise RuntimeError("не удалось восстановить ни одного тензора")
    return out


def _materialize(t: _TensorStub, blobs: dict[str, bytes]) -> np.ndarray:
    storage = t.storage
    if not isinstance(storage, _StorageStub) or not storage.location:
        raise RuntimeError(f"неизвестный storage для тензора offset={t.offset}")
    blob = blobs.get(storage.location)
    if blob is None:
        raise RuntimeError(f"нет блока {storage.location} в архиве")
    dt = t.dtype
    itemsize = np.dtype(dt).itemsize
    n = int(np.prod(t.size, dtype=np.int64))
    flat = np.frombuffer(blob, dtype=dt, count=n, offset=t.offset * itemsize)
    arr = flat.astype(np.float32).reshape(t.size)
    if t.stride != _c_contiguous_strides(t.size):
        # редкий случай: не-контигуозные тензоры
        raise RuntimeError("non-contiguous тензор — не поддерживается")
    return np.ascontiguousarray(arr)


def _c_contiguous_strides(size):
    s = [1]
    for d in reversed(size[:-1]):
        s.append(s[-1] * d)
    return tuple(reversed(s))


# --------------------------------------------------------------------------
# Конвертация GPT-2 -> наши имена
# --------------------------------------------------------------------------

def convert_gpt2(sd: dict[str, np.ndarray], cfg: GPTConfig) -> dict[str, np.ndarray]:
    n_layer = cfg.n_layer
    w: dict[str, np.ndarray] = {
        "wte": sd["transformer.wte.weight"],
        "wpe": sd["transformer.wpe.weight"][:cfg.block_size],
    }
    for i in range(n_layer):
        p = f"transformer.h.{i}."
        w[f"ln1_{i}.w"] = sd[p + "ln_1.weight"]
        w[f"ln1_{i}.b"] = sd[p + "ln_1.bias"]
        w[f"attn_{i}.wqkv"] = sd[p + "attn.c_attn.weight"]
        w[f"attn_{i}.bqkv"] = sd[p + "attn.c_attn.bias"]
        w[f"attn_{i}.wo"] = sd[p + "attn.c_proj.weight"]
        w[f"ln2_{i}.w"] = sd[p + "ln_2.weight"]
        w[f"ln2_{i}.b"] = sd[p + "ln_2.bias"]
        w[f"mlp_{i}.w1"] = sd[p + "mlp.c_fc.weight"]
        w[f"mlp_{i}.b1"] = sd[p + "mlp.c_fc.bias"]
        w[f"mlp_{i}.w2"] = sd[p + "mlp.c_proj.weight"]
        w[f"mlp_{i}.b2"] = sd[p + "mlp.c_proj.bias"]
    w["lnf.w"] = sd["transformer.ln_f.weight"]
    w["lnf.b"] = sd["transformer.ln_f.bias"]
    for k in w:
        w[k] = np.ascontiguousarray(w[k].astype(np.float32))
    return w


# --------------------------------------------------------------------------
# Установка пресетов
# --------------------------------------------------------------------------

PRESETS = {
    "gpt2": dict(
        repo="openai-community/gpt2",
        desc="GPT-2 124M (OpenAI, MIT): ~550 МБ, английский + немного других",
        n_layer=12, n_head=12, n_embd=768, block_size=512,
        vocab_size=50257,
    ),
}


def install(lib: ModelLib, preset: str, name: str | None = None,
            quantize: bool = True) -> str:
    cfg_d = PRESETS[preset]
    repo = cfg_d["repo"]
    pdir = lib.root / "presets" / preset
    pdir.mkdir(parents=True, exist_ok=True)

    _download(f"{HF_BASE}/{repo}/resolve/main/config.json", pdir / "config.json")
    _download(f"{HF_BASE}/{repo}/resolve/main/vocab.json", pdir / "vocab.json")
    _download(f"{HF_BASE}/{repo}/resolve/main/merges.txt", pdir / "merges.txt")

    cfg = GPTConfig(vocab_size=cfg_d["vocab_size"], block_size=cfg_d["block_size"],
                    n_layer=cfg_d["n_layer"], n_head=cfg_d["n_head"],
                    n_embd=cfg_d["n_embd"])

    wpath_st = pdir / "model.safetensors"
    wpath_pt = pdir / "pytorch_model.bin"
    if _exists_remote(f"{HF_BASE}/{repo}/resolve/main/model.safetensors"):
        _download(f"{HF_BASE}/{repo}/resolve/main/model.safetensors", wpath_st)
    if not wpath_st.exists():
        _download(f"{HF_BASE}/{repo}/resolve/main/pytorch_model.bin", wpath_pt)

    if wpath_st.exists():
        sd = load_safetensors(wpath_st)
        src = "safetensors"
    else:
        sd = load_torch_bin(wpath_pt)
        src = "pytorch_model.bin"

    print(f"[preset] веса: {src}, тензоров: {len(sd)}")
    w = convert_gpt2(sd, cfg)
    tok = GPT2Tokenizer.from_files(pdir / "vocab.json", pdir / "merges.txt")

    meta = dict(
        name=name or preset, preset=preset,
        config=cfg.__dict__, params=cfg.n_params(),
        created=time.strftime("%Y-%m-%d %H:%M"),
        source=f"{repo} ({src})",
    )
    model_name = name or preset
    lib.save(model_name, w, meta, tok, quantize=quantize)
    d = lib.models_dir / model_name
    print(f"[preset] готово: {model_name} "
          f"({(d / 'weights.bin').stat().st_size / 2**20:.0f} МБ на диске, "
          f"int8={'да' if quantize else 'нет'}). Можно: python llm.py chat --model {model_name}")
    return model_name


def _exists_remote(url: str) -> bool:
    import urllib.error
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def list_presets() -> None:
    for k, v in PRESETS.items():
        print(f"  {k:<8} {v['desc']}")
