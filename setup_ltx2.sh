#!/usr/bin/env bash
#
# Установка окружения для LTX-2 photo→video агента.
#
# 1) Клонирует LTX-2 (Lightricks) и ставит зависимости (uv sync).
# 2) Скачивает веса модели LTX-2.3 (нужен доступ к Hugging Face +
#    согласие на условия использования gated-репозитория).
# 3) Ставит Silero TTS (озвучка).
#
# Требования:
#   - Python 3.11+
#   - GPU NVIDIA c достаточным VRAM (рекомендуется 24+ GB; см. --offload/--quantization)
#   - uv (https://docs.astral.sh/uv/) и huggingface_hub (`pip install -U huggingface_hub`)
#
# Перед запуском:  hf auth login  (токен Read с доступом к gated-репозиториям)
#
set -euo pipefail

LTX2_DIR="${LTX2_DIR:-LTX-2}"
MODEL_DIR="models/ltx-2.3"
GEMMA_DIR="models/gemma-3-12b"

echo "== 1/4 Клонирую LTX-2 =="
if [ ! -d "$LTX2_DIR" ]; then
  git clone --depth 1 https://github.com/Lightricks/LTX-2.git "$LTX2_DIR"
fi
cd "$LTX2_DIR"

echo "== 2/4 Устанавливаю зависимости (uv sync) =="
uv sync --frozen
source .venv/bin/activate

echo "== 3/4 Скачиваю веса LTX-2.3 (это десятки GB) =="
mkdir -p "$MODEL_DIR" "$GEMMA_DIR"
hf download Lightricks/LTX-2.3 \
    ltx-2.3-22b-dev.safetensors \
    ltx-2.3-spatial-upscaler-x2-1.1.safetensors \
    ltx-2.3-22b-distilled-lora-384-1.1.safetensors \
    --local-dir "$MODEL_DIR"
hf download google/gemma-3-12b-it-qat-q4_0-unquantized --local-dir "$GEMMA_DIR"

echo "== 4/4 Ставлю Silero TTS (озвучка) =="
pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu

echo ""
echo "Готово. Теперь запустите агента из КОРНЯ репозитория (не из LTX-2):"
echo "  export PYTHONPATH=$PWD"
echo "  python ltx2_agent.py --photo me.jpg --text \"Я родилась 05 февраля 1987 года и я красотка\""
echo ""
echo "На GPU с малой памятью добавьте: --offload cpu  и/или  --quantization fp8-cast"
