#!/usr/bin/env bash
# Запуск движка модели для OpenClaw без Ollama (llama.cpp).
# macOS / Linux.
#
#   brew install llama.cpp                 # macOS
#   bash openclaw/start-llama-server.sh    # запуск
#
# Модель скачается с Hugging Face один раз и закэшируется.

set -euo pipefail

# ── Настройки ────────────────────────────────────────────────────────────
# Подберите модель под объём RAM/VRAM:
#   8 ГБ    unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M
#   16 ГБ   unsloth/Qwen3-8B-GGUF:Q4_K_M          <- по умолчанию
#   24-32   unsloth/Qwen3-14B-GGUF:Q4_K_M
#   32+     unsloth/gpt-oss-20b-GGUF:Q4_K_M
MODEL="${MODEL:-unsloth/Qwen3-8B-GGUF:Q4_K_M}"

PORT="${PORT:-8080}"
HOST="${HOST:-127.0.0.1}"
CTX="${CTX:-32768}"          # < 16384 ставить нельзя: промпт OpenClaw сам съедает 6-12k
ALIAS="${ALIAS:-local-model}" # должен совпадать с models.providers.llamacpp.models[].id
NGL="${NGL:-99}"             # слоёв на GPU; 0 = только CPU

# ── Проверки ─────────────────────────────────────────────────────────────
if ! command -v llama-server >/dev/null 2>&1; then
  echo "ОШИБКА: llama-server не найден в PATH."
  echo
  echo "  macOS:  brew install llama.cpp"
  echo "  Linux:  бинарники — https://github.com/ggml-org/llama.cpp/releases"
  exit 1
fi

if command -v lsof >/dev/null 2>&1 && lsof -i ":${PORT}" >/dev/null 2>&1; then
  echo "ВНИМАНИЕ: порт ${PORT} уже занят. Возможно, сервер уже запущен."
  echo "Проверка: curl http://${HOST}:${PORT}/v1/models"
  exit 1
fi

# ── Запуск ───────────────────────────────────────────────────────────────
echo "Модель:     ${MODEL}"
echo "Адрес:      http://${HOST}:${PORT}/v1"
echo "Контекст:   ${CTX}"
echo "ID модели:  ${ALIAS}   (это же значение — в openclaw.json)"
echo
echo "Первый запуск скачивает модель — это может занять несколько минут."
echo

# --jinja ОБЯЗАТЕЛЕН: без него не работает tool calling, а OpenClaw без инструментов бесполезен.
exec llama-server \
  -hf "${MODEL}" \
  --jinja \
  -c "${CTX}" \
  -ngl "${NGL}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --alias "${ALIAS}"
