#!/usr/bin/env bash
# Brand Factory OS — самозапускающийся sh
# chmod +x run_brand_factory.sh && ./run_brand_factory.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PORT=${PORT:-8002}

echo "[BrandFactory] Проверка Python..."
if ! command -v python3 &> /dev/null; then
  echo "Python3 не найден"
  exit 1
fi

echo "[BrandFactory] Ставлю зависимости если нужно..."
python3 -m pip install --break-system-packages -q fastapi "uvicorn[standard]" pydantic python-multipart 2>/dev/null || python3 -m pip install -q fastapi "uvicorn[standard]" pydantic python-multipart

echo "[BrandFactory] Стартуем на http://localhost:$PORT"
echo "[BrandFactory] Пример: brand_factory/projects/demo_example/artifacts/07_brand_manifest.md"
echo "[BrandFactory] Доку: brand_factory/docs/ANALYSIS_FULL.md"
echo ""
python3 -m brand_factory.server
