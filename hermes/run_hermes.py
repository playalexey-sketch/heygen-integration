"""
Запуск локального веб-чата Hermes (через Ollama) из любой папки.

    python run_hermes.py     (или run_hermes.bat)
    открыть: http://localhost:8002

Добавляет папку проекта в sys.path, поэтому работает откуда угодно.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

if __name__ == "__main__":
    os.chdir(HERE)
    from chat_app import app

    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8002"))
    print(f"\n  Hermes Local Chat:  http://localhost:{port}")
    print("  Убедитесь, что Ollama запущен (install_hermes.bat)\n")
    uvicorn.run(app, host=host, port=port)
