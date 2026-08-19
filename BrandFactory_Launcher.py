#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BrandFactory_Launcher.py — ОДИН ФАЙЛ = ВЕСЬ ПРОЕКТ ЗАПУСКАЕТСЯ

Windows: двойной клик
Mac/Linux: python3 BrandFactory_Launcher.py

Сделает:
- проверит/поставит зависимости
- создаст папку проектов если нет
- скопирует demo_example если нет
- запустит веб-фабрику на http://localhost:8002
- откроет браузер

Проект после запуска:
- 7 фаз, 21 агент, единый интерфейс с Approve
- Пример Phase1 уже прогнан (20 артефактов)
- Интеграция HeyGen для видео-аватаров (Phase6)

Для проверки: открой http://localhost:8002 → создай проект → Phase1 → Run агентов по очереди → Approve → смотри Brand Manifest
"""
import os, sys, subprocess, pathlib, time, webbrowser

ROOT = pathlib.Path(__file__).parent
PORT = 8002

def ensure():
    try:
        import fastapi, uvicorn
    except ImportError:
        print("→ Ставлю fastapi uvicorn pydantic python-multipart ...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "fastapi", "uvicorn[standard]", "pydantic", "python-multipart"])
        except:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn[standard]", "pydantic", "python-multipart"])

def main():
    ensure()
    os.chdir(ROOT)
    print(f"\n🚀 Brand Factory OS стартует на http://localhost:{PORT}")
    print(f"📁 Проект: {ROOT / 'brand_factory'}")
    print(f"📦 Пример артефактов: brand_factory/projects/demo_example/artifacts/07_brand_manifest.md")
    print(f"📜 Анализ: brand_factory/docs/ANALYSIS_FULL.md")
    print(f"💡 Логика: каждый агент имеет единый интерфейс: входы md/json/image → выходы → Approve → следующий")
    print("\nНажми Ctrl+C чтобы остановить\n")

    def open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(f"http://localhost:{PORT}")
        except:
            pass

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn
    uvicorn.run("brand_factory.server:app", host="0.0.0.0", port=PORT, reload=False)

if __name__ == "__main__":
    main()
