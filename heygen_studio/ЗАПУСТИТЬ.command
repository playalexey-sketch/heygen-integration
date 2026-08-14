#!/bin/bash
cd "$(dirname "$0")"
echo ""
echo "  Запускаю HeyGen Студию..."
echo ""
if command -v python3 >/dev/null 2>&1; then python3 start.py
elif command -v python >/dev/null 2>&1; then python start.py
else echo "  [!] Python не найден. Установите с https://www.python.org/downloads/"; read -n1; fi
