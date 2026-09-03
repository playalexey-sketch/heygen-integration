"""
Чат и генерация. Здесь собирается «всё в одном»:
  * модель читает веса через OffloadCache (RAM <-> диск),
  * история разговора хранится на диске, в контекст подгружается
    только последний кусок (block_size токенов),
  * KV-кэш — небольшой, живёт в RAM.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

from .diskstore import ModelLib, OffloadCache
from .gpt import GPT, GPTConfig, KVCache, sample_token
from .tokenizer import load_tokenizer

HISTORY_FILE = "history.bin"


def default_data_dir() -> Path:
    return Path(os.environ.get("PERSONAL_LLM_DIR",
                               Path.home() / ".cache" / "personal-llm"))


def total_ram_bytes() -> int:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            class _MSTATUS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            st = _MSTATUS()
            st.dwLength = ctypes.sizeof(_MSTATUS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.ullTotalPhys)
        except Exception:
            pass
    return 8 * 2**30  # предположение по умолчанию


class ChatSession:
    def __init__(self, model_name: str, data_dir: Path, ram_mb: float | None = None,
                 temp: float = 0.9, top_k: int = 40, max_new: int = 200,
                 show_offload: bool = False, use_history: bool = True):
        self.lib = ModelLib(data_dir)
        self.model_name = model_name
        self.store, self.meta, self.mdir = self.lib.open(model_name)
        cfg = GPTConfig(**{k: int(v) for k, v in self.meta["config"].items()})
        self.cfg = cfg

        if ram_mb is None:
            ram_mb = min(512.0, max(128.0, total_ram_bytes() / 2**20 * 0.25))
        self.cache = OffloadCache(self.store, int(ram_mb * 2**20),
                                  verbose=show_offload)
        self.model = GPT(cfg, None, weight_getter=self.cache.get)
        self.tok = load_tokenizer(self.mdir)
        self.temp = temp
        self.top_k = top_k
        self.max_new = max_new
        self.rng = np.random.default_rng()
        self.kv = KVCache(cfg)
        self.history_path = data_dir / model_name / HISTORY_FILE
        self.ctx = []  # ids текущего контекста (последние block_size)
        if use_history:
            self._load_history()

    # ---- история на диске ----

    def _load_history(self):
        if not self.history_path.exists():
            return 0
        raw = self.history_path.read_bytes()
        if not raw:
            return 0
        all_ids = np.frombuffer(raw, dtype=np.int32).tolist()
        n_total = len(all_ids)
        self.ctx = all_ids[-self.cfg.block_size:]
        return n_total

    def _append_history(self, ids: list[int]):
        if not ids:
            return
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "ab") as f:
            f.write(np.asarray(ids, np.int32).tobytes())

    def reset(self):
        self.ctx = []
        self.kv = KVCache(self.cfg)

    # ---- генерация ----

    def generate(self, prompt_ids: list[int], max_new: int | None = None,
                 on_token=None) -> str:
        cfg = self.cfg
        prompt_ids = prompt_ids[-cfg.block_size:]
        max_new = max_new or self.max_new

        self.kv = KVCache(cfg)
        t0 = time.time()
        if prompt_ids:
            h = self.model.forward_prefix(prompt_ids, self.kv)
            pos = len(prompt_ids)
            logits = self.model.logits_from_hidden(h)
        else:
            pos = 0
            h = self.model.embed(0, 0)
            h, logits = self.model.forward_token(h, self.kv)
            pos = 1
        out_ids: list[int] = []

        for _ in range(max_new):
            if pos >= cfg.block_size:
                break
            tid = sample_token(logits, self.temp, self.top_k, self.rng)
            out_ids.append(tid)
            if on_token:
                on_token(tid)
            if pos >= cfg.block_size - 1:
                break
            h = self.model.embed(tid, pos)
            pos += 1
            h, logits = self.model.forward_token(h, self.kv)

        dt = max(time.time() - t0, 1e-9)
        self._last_stats = dict(tokens=len(out_ids), seconds=dt,
                                tok_s=len(out_ids) / dt)
        text = self.tok.decode(out_ids)
        # контекст: храним на диске всё, в RAM — хвост
        self._append_history(prompt_ids + out_ids)
        self.ctx = (prompt_ids + out_ids)[-cfg.block_size:]
        return text

    def info_lines(self) -> list[str]:
        cfg = self.cfg
        disk_mb = self.store.disk_size_mb()
        quant = self.meta.get("quantized")
        return [
            f"модель: {self.model_name}  ({cfg.n_layer} слоёв, "
            f"~{cfg.n_params() / 1e6:.1f}M параметров)",
            f"веса на диске: {disk_mb:.1f} МБ (int8={ 'да' if quant else 'нет' }), "
            f"бюджет RAM: {self.cache.budget / 2**20:.0f} МБ — "
            f"подгружается только то, что нужно",
            f"история: {(self.history_path.stat().st_size / 1024) if self.history_path.exists() else 0:.0f} КБ на диске, "
            f"в контексте: {len(self.ctx)} из {cfg.block_size} токенов",
        ]


def run_chat(data_dir: Path, model_name: str, ram_mb: float | None,
             temp: float, top_k: int, max_new: int, show_offload: bool,
             use_history: bool = True) -> None:
    s = ChatSession(model_name, data_dir, ram_mb=ram_mb, temp=temp, top_k=top_k,
                    max_new=max_new, show_offload=show_offload,
                    use_history=use_history)
    print("=" * 64)
    print("  Личный LLM (local, disk-backed)")
    for line in s.info_lines():
        print(f"  {line}")
    print("  команды: /reset /stats /exit")
    print("=" * 64)

    while True:
        try:
            user = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user in ("/exit", "/quit", "/q"):
            break
        if user == "/reset":
            s.reset()
            print("(контекст очищен, история на диске сохранена)")
            continue
        if user == "/stats":
            print("  " + s.cache.stats_str())
            continue
        # контекст = хвост истории (с диска) + новая реплика
        prompt_ids = s.ctx + s.tok.encode(user)
        sys.stdout.write("Модель: ")
        sys.stdout.flush()
        buf: list[int] = []

        def on_token(tid):
            buf.append(tid)
            if len(buf) % 4 == 0 or tid == 0:
                sys.stdout.write(s.tok.decode(buf))
                sys.stdout.flush()
                buf.clear()

        text = s.generate(prompt_ids)
        if buf:
            sys.stdout.write(s.tok.decode(buf))
        sys.stdout.write("\n" if not text.endswith("\n") else "")
        sys.stdout.flush()
