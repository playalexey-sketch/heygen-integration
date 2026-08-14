#!/bin/bash
cd "$(dirname "$0")"
echo ""
echo "  Тестовый режим: кредиты HeyGen не расходуются."
echo ""
if command -v python3 >/dev/null 2>&1; then python3 start.py --test
else python start.py --test; fi
