"""Тесты дискового хранилища и LRU-выгрузки."""
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from personal_llm.diskstore import OffloadCache, WeightStore  # noqa: E402


def test_roundtrip(tmp: Path):
    rng = np.random.default_rng(0)
    w = {
        "wte": rng.normal(0, 0.02, (100, 16)).astype(np.float32),
        "attn_0.wo": rng.normal(0, 0.02, (16, 16)).astype(np.float32),
        "lnf.b": np.zeros(16, np.float32),
    }
    p = tmp / "w.bin"
    WeightStore.create(p, w, {"a": 1}, quantize=False)
    st = WeightStore(p)
    for k, v in w.items():
        np.testing.assert_allclose(st.read(k), v, rtol=1e-6)
    assert st.meta == {"a": 1}
    print("OK: float32 roundtrip")


def test_quant(tmp: Path):
    rng = np.random.default_rng(0)
    w = {"big": rng.normal(0, 1.0, (300, 32)).astype(np.float32),
         "zero": np.zeros(8, np.float32)}
    p = tmp / "q.bin"
    WeightStore.create(p, w, {}, quantize=True)
    st = WeightStore(p)
    for k, v in w.items():
        got = st.read(k)
        err = np.abs(got - v).max() / (np.abs(v).max() + 1e-9)
        assert err < 0.02, f"{k}: int8-ошибка {err}"
    print("OK: int8 roundtrip (макс. отн. ошибка < 2%)")


def test_lru():
    tmp = Path(tempfile.mkdtemp())
    rng = np.random.default_rng(1)
    # 8 тензоров по ~1 МБ
    w = {f"t{i}": rng.normal(0, 1, (256, 1024)).astype(np.float32) for i in range(8)}
    p = tmp / "w.bin"
    WeightStore.create(p, w, {}, quantize=False)
    st = WeightStore(p)

    # бюджет 2 МБ -> в RAM поместятся 2 тензора
    c = OffloadCache(st, 2 * 2**20)
    for i in range(8):
        a = c.get(f"t{i}")
        np.testing.assert_allclose(a, w[f"t{i}"], rtol=1e-6)
    assert c.hits == 0 and c.misses == 8
    assert c.evictions >= 6
    # повторное чтение последних — попадания
    c.get("t7"); c.get("t6")
    assert c.hits == 2
    # вытесненный должен читаться с диска заново
    m0 = c.misses
    c.get("t0")
    assert c.misses == m0 + 1
    assert c.ram_bytes <= 2 * 2**20 * 1.001 + 0
    print(f"OK: LRU (misses={c.misses}, evictions={c.evictions}, "
          f"ram={c.ram_bytes / 2**20:.2f} МБ)")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        test_roundtrip(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_quant(Path(d))
    test_lru()
    print("все тесты хранилища прошли")
