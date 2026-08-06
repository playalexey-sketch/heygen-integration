#!/usr/bin/env bash
#
# Быстрый старт развёртывания LTX-2 агента в облаке.
# Делает: проверка GPU → установка зависимостей → скачивание весов → запуск.
#
# Запуск:
#   bash deploy/quick_start.sh
#
set -euo pipefail

echo "== 0. Проверяю GPU =="
if ! nvidia-smi >/dev/null 2>&1; then
  echo "❌ GPU не найден (nvidia-smi не отвечает). Убедитесь, что машина имеет GPU."
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1

echo ""
echo "== 1. Устанавливаю зависимости =="
python3 -m venv .venv || true
source .venv/bin/activate
pip install -q -r requirements.txt
pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -q omegaconf

echo ""
echo "== 2. Проверяю веса модели =="
if [ -f "models/ltx-2.3/ltx-2.3-22b-dev.safetensors" ]; then
  echo "✅ Веса уже есть."
else
  echo "⚠️ Веса не найдены. Скачиваю (нужен HF_TOKEN)…"
  bash deploy/download_models.sh
fi

echo ""
echo "== 3. Запускаю веб-интерфейс на :8001 =="
export HOST=0.0.0.0 PORT=8001
export LTX2_OUTPUT_DIR="${LTX2_OUTPUT_DIR:-ltx2_output}"
python run_webui.py
