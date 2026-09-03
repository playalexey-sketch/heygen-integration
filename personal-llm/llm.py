#!/usr/bin/env python3
"""
Мой личный LLM — маленький Transformer, который живёт на вашем компе.

Принцип: ВСЕ веса на диске, в RAM подгружается только то, что нужно
(LRU-кэш, --ram-mb). История разговора тоже на диске.

Быстрый старт:
  python llm.py train --data data_example/moi_zapiski.txt --name moi
  python llm.py chat  --model moi

Список команд: python llm.py help
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from personal_llm.chat import ChatSession, default_data_dir, run_chat  # noqa: E402
from personal_llm.diskstore import ModelLib, OffloadCache             # noqa: E402
from personal_llm.gpt import GPT, GPTConfig, KVCache, sample_token    # noqa: E402
from personal_llm.train import PRESETS, train                         # noqa: E402
from personal_llm.tokenizer import load_tokenizer                     # noqa: E402


def _data_dir(args) -> Path:
    return Path(args.data_dir).expanduser() if args.data_dir else default_data_dir()


# --------------------------------------------------------------------------

def cmd_train(args):
    text = []
    for p in args.data:
        text.append(Path(p).read_text(encoding="utf-8", errors="replace"))
    lib = ModelLib(_data_dir(args))
    train(text, args.name, lib, preset=args.preset, vocab_size=args.vocab,
          tokens=args.tokens, batch=args.batch, lr=args.lr, seed=args.seed,
          quantize=args.quant, use_bpe=not args.bytes)
    print(f"\nПопробуйте:  python llm.py chat --model {args.name}")


def cmd_chat(args):
    lib = ModelLib(_data_dir(args))
    name = args.model or lib.latest()
    if not name:
        sys.exit("Модель не найдена. Сначала: python llm.py train --data ... --name moi")
    run_chat(_data_dir(args), name, ram_mb=args.ram_mb, temp=args.temp,
             top_k=args.top_k, max_new=args.max_new, show_offload=args.show_offload,
             use_history=not args.no_history)


def cmd_gen(args):
    lib = ModelLib(_data_dir(args))
    name = args.model or lib.latest()
    if not name:
        sys.exit("Модель не найдена. Сначала: python llm.py train --data ... --name moi")
    s = ChatSession(name, _data_dir(args), ram_mb=args.ram_mb, temp=args.temp,
                    top_k=args.top_k, max_new=args.max_new,
                    show_offload=args.show_offload, use_history=not args.no_history)
    prompt_ids = (s.ctx + s.tok.encode(args.text)) if not args.no_history else s.tok.encode(args.text)
    print(s.tok.decode([]), end="")
    print("Модель:", s.generate(prompt_ids))
    print("---", s.cache.stats_str())


def cmd_info(args):
    lib = ModelLib(_data_dir(args))
    names = lib.list()
    if not names:
        print("Моделей пока нет. Обучение: python llm.py train --data ... --name moi")
        return
    if args.model:
        names = [args.model]
    for name in names:
        store, meta, d = lib.open(name)
        cfg = GPTConfig(**{k: int(v) for k, v in meta["config"].items()})
        wb = d / "weights.bin"
        print(f"== {name} ==")
        print(f"   источник:      {meta.get('source', '?')}")
        print(f"   параметров:    {cfg.n_params() / 1e6:.2f}M")
        print(f"   архитектура:   {cfg.n_layer}x{cfg.n_head}h, embd={cfg.n_embd}, "
              f"ctx={cfg.block_size}, vocab={cfg.vocab_size}")
        print(f"   файл на диске: {wb} ({store.disk_size_mb():.1f} МБ, "
              f"int8={'да' if meta.get('quantized') else 'нет'})")
        if meta.get("final_loss") is not None:
            print(f"   финальный loss: {meta['final_loss']} "
                  f"({meta.get('train_tokens', '?')} токенов)")
        print(f"   токенайзер:    {meta.get('tokenizer')}")
        print()


def cmd_presets(args):
    from personal_llm import presets
    if args.preset_name == "list":
        print("Доступные открытые пресеты (нужен интернет):")
        presets.list_presets()
        return
    lib = ModelLib(_data_dir(args))
    presets.install(lib, args.preset_name, name=args.name, quantize=not args.float32)


# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        prog="llm.py",
        description="Мой личный LLM: маленький GPT, который живёт на вашем компе "
                    "и подгружает из RAM только то, что нужно (остальное — на диске).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--data-dir", help="каталог для моделей (по умолчанию ~/.cache/personal-llm)")
    sub = ap.add_subparsers(dest="cmd")

    t = sub.add_parser("train", help="обучить модель на вашем тексте")
    t.add_argument("--data", nargs="+", required=True, help="текстовые файлы (zаметки, статьи...)")
    t.add_argument("--name", required=True, help="имя модели, напр. moi")
    t.add_argument("--preset", choices=list(PRESETS), default="micro")
    t.add_argument("--tokens", type=int, default=60_000, help="сколько токенов показать модели")
    t.add_argument("--vocab", type=int, default=512, help="размер BPE-словаря")
    t.add_argument("--batch", type=int, default=16)
    t.add_argument("--lr", type=float, default=3e-4)
    t.add_argument("--seed", type=int, default=1337)
    t.add_argument("--quant", action="store_true", help="хранить веса int8 (x4 меньше)")
    t.add_argument("--bytes", action="store_true", help="байтовый токенайзер вместо BPE")
    t.set_defaults(func=cmd_train)

    c = sub.add_parser("chat", help="поговорить с моделью")
    c.add_argument("--model", help="имя модели (по умолчанию последняя)")
    c.add_argument("--ram-mb", type=float, default=None,
                   help="бюджет RAM для весов, МБ (по умолчанию 25%% RAM, до 512)")
    c.add_argument("--temp", type=float, default=0.9)
    c.add_argument("--top-k", type=int, default=40)
    c.add_argument("--max-new", type=int, default=200)
    c.add_argument("--show-offload", action="store_true",
                   help="показывать, что подгружается с диска, а что вытесняется")
    c.add_argument("--no-history", action="store_true", help="не читать историю с диска")
    c.set_defaults(func=cmd_chat)

    g = sub.add_parser("gen", help="одноразовая генерация")
    g.add_argument("--text", required=True)
    g.add_argument("--model")
    g.add_argument("--ram-mb", type=float, default=None)
    g.add_argument("--temp", type=float, default=0.9)
    g.add_argument("--top-k", type=int, default=40)
    g.add_argument("--max-new", type=int, default=150)
    g.add_argument("--show-offload", action="store_true")
    g.add_argument("--no-history", action="store_true")
    g.set_defaults(func=cmd_gen)

    i = sub.add_parser("info", help="про модели")
    i.add_argument("--model")
    i.set_defaults(func=cmd_info)

    p = sub.add_parser("presets", help="готовые открытые модели (интернет)")
    p.add_argument("preset_name", nargs="?", default="list",
                   help="list | gpt2")
    p.add_argument("--name", help="имя локальной модели (по умолчанию gpt2)")
    p.add_argument("--float32", action="store_true", help="не квантовать в int8")
    p.set_defaults(func=cmd_presets)

    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help()
        lib = ModelLib(default_data_dir())
        names = lib.list()
        if names:
            print("Ваши модели:", ", ".join(names))
        else:
            print("\nМоделей пока нет. Начните с примера:")
            print("  python llm.py train --data data_example/moi_zapiski.txt --name moi")
            print("  python llm.py chat --model moi")
        return
    args.func(args)


if __name__ == "__main__":
    main()
