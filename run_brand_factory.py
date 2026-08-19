#!/usr/bin/env python3
"""
Brand Factory OS — Самозапускающийся файл
Двойной клик / python run_brand_factory.py → ставит зависимости и стартует фабрику на http://localhost:8002

Что делает:
1. Проверяет Python 3.10+
2. Ставит fastapi uvicorn pydantic python-multipart если нет
3. Запускает brand_factory/server.py на 0.0.0.0:8002
4. Открывает браузер
"""
import sys, os, subprocess, time, webbrowser, pathlib

ROOT = pathlib.Path(__file__).parent
PORT = int(os.getenv("PORT", "8002"))
HOST = os.getenv("HOST", "0.0.0.0")

def log(msg): print(f"[BrandFactory] {msg}")

def ensure_deps():
    try:
        import fastapi, uvicorn, pydantic  # noqa
        log("Зависимости уже установлены ✓")
        return True
    except ImportError:
        log("Ставлю зависимости fastapi uvicorn pydantic python-multipart ...")
        try:
            # пробуем с --break-system-packages для Linux системных окружений
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "fastapi", "uvicorn[standard]", "pydantic", "python-multipart"])
        except Exception:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn[standard]", "pydantic", "python-multipart"])
        log("Зависимости установлены ✓")
        return True

def main():
    log(f"ROOT: {ROOT}")
    if sys.version_info < (3, 9):
        print("Нужен Python 3.9+")
        sys.exit(1)

    ensure_deps()

    # Проверка файлов фабрики
    bf_dir = ROOT / "brand_factory"
    if not bf_dir.exists():
        print(f"Не найдена папка {bf_dir} — запусти из корня репо")
        sys.exit(1)

    # Создаем .gitkeep для projects если нет
    (bf_dir / "projects").mkdir(exist_ok=True)

    url = f"http://localhost:{PORT}"
    log(f"Стартуем Brand Factory OS на {url}")
    log(f"Preview для Arena/E2B: http://0.0.0.0:{PORT}")
    log("Открой в браузере: вкладки Phase1..Phase7, Overview, Factory Graph, Artifacts, Journey Map")
    log("Если хочешь сменить порт: PORT=8003 python run_brand_factory.py")
    log("Логи ниже — Ctrl+C чтобы остановить")
    print("\n" + "="*60)
    print(f"🚀 Brand Factory OS → {url}")
    print(f"📦 Пример проекта: brand_factory/projects/demo_example/artifacts/")
    print(f"📜 Анализ пути: brand_factory/docs/ANALYSIS_FULL.md")
    print("="*60 + "\n")

    # Открываем браузер через 1.5 сек в отдельном потоке
    def open_browser():
        time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    # Запускаем сервер
    os.chdir(ROOT)
    try:
        import uvicorn
        uvicorn.run("brand_factory.server:app", host=HOST, port=PORT, reload=False)
    except KeyboardInterrupt:
        log("Остановлено")

if __name__ == "__main__":
    main()
