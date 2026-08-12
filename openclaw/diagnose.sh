#!/usr/bin/env bash
# Диагностика связки OpenClaw + Telegram + движок модели (Ollama / llama.cpp).
# Проходит цепочку сверху вниз и говорит, на каком звене обрыв.
#
#   bash openclaw/diagnose.sh
#
# Скрипт ничего не меняет — только читает.

OK="[ OK ]"; BAD="[FAIL]"; WARN="[WARN]"; INFO="[INFO]"
PROBLEMS=0

hr()      { printf '\n──────────────────────────────────────────────────────\n%s\n──────────────────────────────────────────────────────\n' "$1"; }
ok()      { echo "$OK   $1"; }
bad()     { echo "$BAD $1"; PROBLEMS=$((PROBLEMS+1)); }
warn()    { echo "$WARN $1"; }
info()    { echo "$INFO $1"; }

CFG="${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}"

# ── 1. Node.js ────────────────────────────────────────────────────────────
hr "1. Node.js"
if command -v node >/dev/null 2>&1; then
  NODE_V=$(node -v | tr -d 'v')
  NODE_MAJOR=${NODE_V%%.*}
  info "Установлен Node ${NODE_V}"
  if [ "$NODE_MAJOR" -ge 26 ] 2>/dev/null; then
    ok "Версия подходит (рекомендуемая — 26)"
  elif [ "$NODE_MAJOR" -ge 22 ] 2>/dev/null; then
    ok "Версия скорее всего подходит (нужно 22.22.3+ / 24.15+ / 25.9+)"
  else
    bad "Node слишком старый. OpenClaw требует 22.22.3+, 24.15+ или 25.9+"
    echo "       Обновите Node: https://nodejs.org/"
  fi
else
  bad "Node.js не найден. Установите с https://nodejs.org/"
fi

# ── 2. OpenClaw CLI ───────────────────────────────────────────────────────
hr "2. OpenClaw CLI"
if command -v openclaw >/dev/null 2>&1; then
  ok "openclaw найден: $(command -v openclaw)"
  info "Версия: $(openclaw --version 2>/dev/null | head -1)"

  COUNT=$(command -v -a openclaw 2>/dev/null | wc -l | tr -d ' ')
  if [ "${COUNT:-1}" -gt 1 ]; then
    warn "В системе несколько бинарников openclaw (split brain):"
    command -v -a openclaw 2>/dev/null | sed 's/^/       /'
    echo "       Это частая причина 'сломалось после обновления'."
    echo "       Лечение: почините PATH, затем: openclaw gateway install --force"
  fi

  TOUCHED=$(openclaw config get meta.lastTouchedVersion 2>/dev/null | tr -d '"' | tr -d ' ')
  [ -n "$TOUCHED" ] && info "Конфиг последний раз писала версия: ${TOUCHED}"
else
  bad "openclaw не найден в PATH"
  echo "       Установка: npm install -g openclaw@latest"
fi

# ── 3. Конфиг ─────────────────────────────────────────────────────────────
hr "3. Конфиг ~/.openclaw/openclaw.json"
if [ -f "$CFG" ]; then
  ok "Найден: $CFG"

  if command -v node >/dev/null 2>&1; then
    node -e "require('fs').readFileSync('$CFG','utf8') && JSON.parse(require('fs').readFileSync('$CFG','utf8'))" 2>/dev/null \
      && ok "JSON валиден" \
      || warn "JSON не парсится строго (допустимо, если это json5 с комментариями)"
  fi

  if grep -q '11434/v1' "$CFG" 2>/dev/null; then
    bad "В конфиге Ollama указан baseUrl с /v1 — это legacy-режим"
    echo "       OpenClaw ходит в НАТИВНЫЙ API Ollama (/api/chat)."
    echo "       Исправьте на: \"baseUrl\": \"http://127.0.0.1:11434\", \"api\": \"ollama\""
  fi

  if grep -q '"ollama"' "$CFG" 2>/dev/null && ! grep -q 'apiKey' "$CFG" 2>/dev/null; then
    warn "У провайдера ollama, похоже, не задан apiKey"
    echo "       Нужно любое непустое значение: openclaw config set models.providers.ollama.apiKey \"ollama-local\""
  fi

  if grep -qE 'ВСТАВЬТЕ|ВАШ_ЧИСЛОВОЙ|YOUR_TOKEN' "$CFG" 2>/dev/null; then
    bad "В конфиге остались placeholder-значения (токен / ID не подставлены)"
  fi
else
  bad "Конфиг не найден: $CFG"
  echo "       Скопируйте шаблон: cp openclaw/configs/openclaw.llamacpp.json $CFG"
fi

# ── 4. Шлюз OpenClaw ──────────────────────────────────────────────────────
hr "4. Шлюз (gateway)"
if command -v openclaw >/dev/null 2>&1; then
  GW=$(openclaw gateway status 2>&1)
  echo "$GW" | sed 's/^/       /' | head -20
  echo "$GW" | grep -qi 'running' && ok "Шлюз запущен" || bad "Шлюз не в состоянии running → openclaw gateway restart"
fi

if command -v curl >/dev/null 2>&1; then
  curl -s -o /dev/null -m 5 http://127.0.0.1:18789 \
    && ok "Порт 18789 отвечает (Control UI доступен)" \
    || warn "Порт 18789 не отвечает"
fi

# ── 5. Ollama ─────────────────────────────────────────────────────────────
hr "5. Движок: Ollama (порт 11434)"
if command -v ollama >/dev/null 2>&1; then
  info "Установлен: $(ollama --version 2>&1 | head -1)"
else
  info "CLI ollama не найден (нормально, если вы перешли на llama.cpp)"
fi

if command -v curl >/dev/null 2>&1; then
  TAGS=$(curl -s -m 5 http://127.0.0.1:11434/api/tags 2>/dev/null)
  if [ -n "$TAGS" ]; then
    ok "Демон Ollama отвечает"
    if command -v ollama >/dev/null 2>&1; then
      MODELS=$(ollama list 2>/dev/null | tail -n +2)
      if [ -n "$MODELS" ]; then
        ok "Скачанные модели:"
        echo "$MODELS" | sed 's/^/       /'
        echo
        echo "       ВАЖНО: имя модели в openclaw.json должно совпадать символ в символ."
      else
        bad "Ollama работает, но моделей нет → ollama pull qwen3:8b"
      fi
    fi
  else
    warn "Демон Ollama на 127.0.0.1:11434 не отвечает"
    echo "       Linux:  sudo systemctl restart ollama"
    echo "       macOS:  ollama serve"
    echo "       (не проблема, если вы намеренно перешли на llama.cpp)"
  fi
fi

if [ -n "${OLLAMA_API_KEY:-}" ]; then
  ok "OLLAMA_API_KEY задан"
else
  warn "OLLAMA_API_KEY не задан — без него провайдер ollama может не включиться"
  echo "       export OLLAMA_API_KEY=\"ollama-local\""
fi

# ── 6. llama.cpp ──────────────────────────────────────────────────────────
hr "6. Движок: llama.cpp (порт 8080)"
if command -v curl >/dev/null 2>&1; then
  LC=$(curl -s -m 5 http://127.0.0.1:8080/v1/models 2>/dev/null)
  if [ -n "$LC" ]; then
    ok "llama-server отвечает на /v1/models"
    echo "$LC" | head -c 500 | sed 's/^/       /'; echo
    echo
    echo "       Значение \"id\" отсюда должно совпадать с models.providers.llamacpp.models[].id"
  else
    info "llama-server на 127.0.0.1:8080 не запущен"
    echo "       Запуск: bash openclaw/start-llama-server.sh"
  fi
fi

# ── 7. Модели глазами OpenClaw ────────────────────────────────────────────
hr "7. Что видит сам OpenClaw"
if command -v openclaw >/dev/null 2>&1; then
  openclaw models status 2>&1 | head -25 | sed 's/^/       /'
fi

# ── 8. Telegram ───────────────────────────────────────────────────────────
hr "8. Канал Telegram"
if command -v openclaw >/dev/null 2>&1; then
  openclaw channels status --probe 2>&1 | head -25 | sed 's/^/       /'
  echo
  info "Ожидающие подтверждения пары:"
  openclaw pairing list telegram 2>&1 | head -10 | sed 's/^/       /'
fi

TOKEN="${TELEGRAM_BOT_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -f "$CFG" ]; then
  TOKEN=$(grep -oE '"botToken"[[:space:]]*:[[:space:]]*"[^"]+"' "$CFG" 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
fi

if [ -n "$TOKEN" ] && [ "${TOKEN#ВСТАВЬТЕ}" = "$TOKEN" ] && command -v curl >/dev/null 2>&1; then
  ME=$(curl -s -m 10 "https://api.telegram.org/bot${TOKEN}/getMe" 2>/dev/null)
  if echo "$ME" | grep -q '"ok":true'; then
    ok "Токен бота валиден"
    echo "$ME" | grep -oE '"username":"[^"]+"' | sed 's/^/       /'
  else
    bad "Telegram отклонил токен (getMe != ok)"
    echo "$ME" | head -c 300 | sed 's/^/       /'; echo
    echo "       Перевыпустите токен в @BotFather и обновите channels.telegram.botToken"
  fi
else
  info "Токен не найден в конфиге/окружении — проверка getMe пропущена"
fi

# ── 9. doctor ─────────────────────────────────────────────────────────────
hr "9. openclaw doctor"
if command -v openclaw >/dev/null 2>&1; then
  openclaw doctor 2>&1 | head -40 | sed 's/^/       /'
fi

# ── Итог ──────────────────────────────────────────────────────────────────
hr "ИТОГ"
if [ "$PROBLEMS" -eq 0 ]; then
  echo "$OK   Явных проблем не найдено."
  echo
  echo "Если бот всё ещё молчит — смотрите живые логи в момент отправки сообщения:"
  echo "    openclaw logs --follow"
else
  echo "$BAD Найдено проблем: ${PROBLEMS}. Разбирайте сверху вниз — первая обычно и есть причина."
fi

echo
echo "Стандартная последовательность починки:"
echo "    openclaw doctor --fix"
echo "    openclaw gateway restart"
echo "    openclaw status --all"
echo "    openclaw logs --follow"
