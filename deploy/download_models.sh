#!/usr/bin/env bash
#
# Скачивает веса LTX-2.3 (нужны для генерации видео) + Gemma text-encoder.
# Требуется доступ к Hugging Face и согласие на gated-репозиторий
# Lightricks/LTX-2.3 (https://huggingface.co/Lightricks/LTX-2.3).
#
# Перед запуском:  pip install -U huggingface_hub  и  hf auth login
# (или укажите HF_TOKEN в окружении).
#
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-models/ltx-2.3}"
GEMMA_DIR="${GEMMA_DIR:-models/gemma-3-12b}"

echo "== Скачиваю LTX-2.3 веса в $MODEL_DIR =="
mkdir -p "$MODEL_DIR" "$GEMMA_DIR"

hf download Lightricks/LTX-2.3 \
    ltx-2.3-22b-dev.safetensors \
    ltx-2.3-spatial-upscaler-x2-1.1.safetensors \
    ltx-2.3-22b-distilled-lora-384-1.1.safetensors \
    --local-dir "$MODEL_DIR"

echo "== Скачиваю Gemma-3-12b text-encoder в $GEMMA_DIR =="
hf download google/gemma-3-12b-it-qat-q4_0-unquantized --local-dir "$GEMMA_DIR"

echo ""
echo "Готово! Веса в:"
echo "  $MODEL_DIR"
echo "  $GEMMA_DIR"
echo "Проверьте, что пути в deploy/.env совпадают."
