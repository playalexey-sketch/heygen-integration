"""End-to-end: обучить микроскопическую модель на синтетическом тексте,
проверить падение loss, генерацию и идентичность инференса «в RAM»
и «через кэш с диском»."""
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from personal_llm.chat import ChatSession                     # noqa: E402
from personal_llm.diskstore import ModelLib, OffloadCache     # noqa: E402
from personal_llm.gpt import GPT, GPTConfig, KVCache, sample_token, cross_entropy  # noqa: E402
from personal_llm.train import train                          # noqa: E402
from personal_llm.tokenizer import BPETokenizer               # noqa: E402

TEXT = ("завтра созвон с командой в десять утра. "
        "не забыть купить хлеб и молоко. "
        "вечером пробежка в парке, погода хорошая. "
        "на работе много задач, нужно расставить приоритеты. "
        "письмо для личного LLM на чистом пайтоне. ") * 60


def main():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        lib = ModelLib(d)
        meta = train([TEXT], "demo", lib, preset="micro", vocab_size=256,
                     tokens=15000, batch=8, log_every=10**9)
        assert meta["final_loss"] < 3.0, f"loss не упал: {meta['final_loss']}"
        print(f"OK: обучение, финальный loss = {meta['final_loss']}")

        # инференс: в RAM и через кэш (одни и те же веса) должны совпасть
        store, m, mdir = lib.open("demo")
        from personal_llm.tokenizer import load_tokenizer
        tok = load_tokenizer(mdir)
        cfg = GPTConfig(**{k: int(v) for k, v in m["config"].items()})

        from personal_llm.diskstore import WeightStore
        ws = WeightStore(mdir / "weights.bin")
        w = {k: ws.read(k) for k in ws.tensor_names}
        model_ram = GPT(cfg, w)

        cache = OffloadCache(ws, 4096)  # крошечный бюджет -> всё с диска
        model_disk = GPT(cfg, None, weight_getter=cache.get)

        # 1) token-декод должен совпадать с полным проходом (KV-кэш честный)
        ids = tok.encode("завтра ")
        kv = KVCache(cfg)
        h = model_ram.forward_prefix(ids, kv)
        seq = list(ids)
        logits_prev = model_ram.logits_from_hidden(h)
        logits_full = model_ram._forward_train(np.array([seq], np.int64))[0]
        np.testing.assert_allclose(logits_prev, logits_full[-1], rtol=1e-4, atol=1e-4)
        for _ in range(4):
            tid = int(sample_token(logits_prev, 1.0, 1))
            pos = len(seq)
            h_emb = model_ram.embed(tid, pos)
            h_t, logits_t = model_ram.forward_token(h_emb, kv)
            seq.append(tid)
            logits_full = model_ram._forward_train(np.array([seq], np.int64))[0]
            np.testing.assert_allclose(logits_t, logits_full[-1], rtol=1e-4, atol=1e-4)
            logits_prev = logits_t
        print("OK: token-декод == полный проход (KV-кэш честный)")

        # 2) инференс через кэш (с диска) == инференс в RAM
        ids = tok.encode("завтра ")
        kv1, kv2 = KVCache(cfg), KVCache(cfg)
        h1 = model_ram.forward_prefix(ids, kv1)
        h2 = model_disk.forward_prefix(ids, kv2)
        np.testing.assert_allclose(h1, h2, rtol=1e-5, atol=1e-5)
        for _ in range(5):
            tid = int(sample_token(model_ram.logits_from_hidden(h1), 1.0, 1))
            pos = kv1.t
            h1, _ = model_ram.forward_token(model_ram.embed(tid, pos), kv1)
            h2, _ = model_disk.forward_token(model_disk.embed(tid, pos), kv2)
            np.testing.assert_allclose(
                model_ram.logits_from_hidden(h1),
                model_disk.logits_from_hidden(h2), rtol=1e-4, atol=1e-4)
        print(f"OK: инференс через кэш = инференс в RAM "
              f"(с диска прочитано {cache.bytes_loaded / 2**20:.1f} МБ, "
              f"промахов {cache.misses})")

        # чат-сессия: генерация работает, история пишется на диск
        s = ChatSession("demo", d, ram_mb=16, temp=1.0, top_k=10, max_new=24)
        out = s.generate(tok.encode("привет"), max_new=24)
        assert len(out) > 0
        assert s.history_path.exists() and s.history_path.stat().st_size > 0
        print(f"OK: генерация: {out[:60]!r}...")
        print("все e2e-проверки прошли")


if __name__ == "__main__":
    main()
