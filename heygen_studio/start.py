#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Запуск HeyGen Студии.

    python start.py              обычный запуск
    python start.py --test       запуск вместе с тестовым сервером-эмулятором
    python start.py --port 8080  другой порт

При первом запуске сам доустановит недостающие библиотеки.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

REQUIRED = [("fastapi", "fastapi"), ("uvicorn", "uvicorn"),
            ("requests", "requests"), ("multipart", "python-multipart")]


def ensure_deps() -> None:
    missing = []
    for mod, pkg in REQUIRED:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    print(f"Устанавливаю недостающие библиотеки: {', '.join(missing)}")
    cmds = [[sys.executable, "-m", "pip", "install", "-q", *missing],
            [sys.executable, "-m", "pip", "install", "-q",
             "--break-system-packages", *missing]]
    for c in cmds:
        try:
            if subprocess.call(c) == 0:
                print("Готово.\n")
                return
        except Exception:
            continue
    print("Не удалось установить автоматически. Выполните вручную:\n"
          f"  pip install {' '.join(missing)}")
    sys.exit(1)


def free_port(start: int, span: int = 40) -> int:
    """Первый свободный порт начиная с указанного."""
    import socket
    for p in range(start, start + span):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def main() -> None:
    ap = argparse.ArgumentParser(description="HeyGen Студия")
    ap.add_argument("--port", type=int, default=int(os.getenv("STUDIO_PORT", "8300")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--test", action="store_true",
                    help="поднять тестовый эмулятор HeyGen и переключиться на него")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    ensure_deps()
    import uvicorn

    # если порт занят другой программой — молча берём следующий свободный
    wanted = args.port
    args.port = free_port(args.port)
    if args.port != wanted:
        print(f"Порт {wanted} занят, использую {args.port}.")

    if args.test:
        mock_port = free_port(8765)
        os.environ["HEYGEN_BASE_URL"] = f"http://127.0.0.1:{mock_port}"
        os.environ.setdefault("HEYGEN_API_KEY", "test_key")
        from mock.mock_heygen import app as mock_app

        def run_mock():
            uvicorn.run(mock_app, host="127.0.0.1", port=mock_port,
                        log_level="warning")
        threading.Thread(target=run_mock, daemon=True).start()
        time.sleep(1.5)
        print(f"Тестовый эмулятор HeyGen запущен на http://127.0.0.1:{mock_port}")

        # тестовый режим прописываем в настройки, чтобы форма сразу работала
        try:
            import json as _json
            cfg_path = HERE / "settings.json"
            cfg = {}
            if cfg_path.is_file():
                cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg["api_key"] = cfg.get("api_key") or "test_key"
            cfg["base_url"] = f"http://127.0.0.1:{mock_port}"
            cfg_path.write_text(_json.dumps(cfg, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        except Exception:
            pass

    from app.server import app

    url = f"http://localhost:{args.port}"
    print("\n" + "═" * 54)
    print("  HeyGen Студия запущена")
    print(f"  Откройте в браузере:  {url}")
    if args.test:
        print("  Режим: ТЕСТОВЫЙ (кредиты не расходуются)")
    print("  Остановить: Ctrl + C")
    print("═" * 54 + "\n")

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
