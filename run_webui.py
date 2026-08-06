"""
Универсальный запуск веб-интерфейса LTX-2 из ЛЮБОЙ папки.

Запуск:
    C:\\Python310\\python.exe run_webui.py

(или просто дважды кликнуть по run_webui.bat в Windows)
Этот файл добавляет папку проекта в sys.path, поэтому не важно, из какой
директории вы его вызываете.
"""

import os
import sys

# Добавляем папку проекта (ту, где лежит этот файл) в sys.path,
# чтобы импорты `webui` и `ltx2` работали из любого места.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

if __name__ == "__main__":
    os.chdir(HERE)  # выходная папка ./ltx2_output будет рядом с проектом
    import uvicorn

    from webui import server

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    print("\n  LTX-2 Photo→Video agent UI:  http://localhost:%d" % port)
    print("  Выходная папка:              %s\n" % os.path.abspath(server.DEFAULT_OUTPUT_DIR))
    uvicorn.run(server.app, host=host, port=port)
