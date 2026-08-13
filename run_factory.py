# -*- coding: utf-8 -*-
"""
Запуск пульта фабрики агентов из любой папки.

    python run_factory.py
    или двойной клик по run_factory.bat

Открыть: http://localhost:8003
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

if __name__ == "__main__":
    os.chdir(HERE)
    import uvicorn
    from factory.server import app

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("FACTORY_PORT") or os.getenv("PORT") or "8003")
    print("\n  Фабрика агентов:  http://localhost:%d" % port)
    print("  Сначала поднимите модель в LM Studio (:1234) или смотрите демо-режим.\n")
    uvicorn.run(app, host=host, port=port)
