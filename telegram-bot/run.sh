#!/usr/bin/env bash
# Запуск бота (Linux / macOS).
#
#   ./run.sh          — два процесса: бот (в терминале) + веб-админка (в фоне)
#   ./run.sh bot      — только Telegram-бот
#   ./run.sh admin    — только веб-админ-панель
set -e
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Не найден $PY. Установите Python 3.10+ и повторите."
  exit 1
fi

# --- 1. виртуальное окружение ---
if [ ! -d venv ]; then
  echo "→ Создаю виртуальное окружение (venv)…"
  "$PY" -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

# --- 2. зависимости ---
echo "→ Проверяю зависимости…"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

# --- 3. конфигурация ---
if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Я создал файл .env из шаблона."
  echo "Впишите в него BOT_TOKEN (и ADMIN_PASSWORD) и запустите ./run.sh ещё раз."
  echo "  Токен бота:  @BotFather → /newbot (или /token)"
  echo "  Ваш Telegram ID: напишите боту @userinfobot"
  exit 0
fi

if grep -q "PASTE_YOUR_BOT_TOKEN" .env; then
  echo
  echo "В .env ещё не вписан BOT_TOKEN. Впишите его в файл .env и запустите ./run.sh ещё раз."
  exit 1
fi

# --- 4. запуск ---
WEB_PORT=$(grep -E "^WEB_PORT=" .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')
WEB_PORT=${WEB_PORT:-8080}

if [ "$1" = "admin" ]; then
  echo "→ Запускаю веб-админ-панель: http://localhost:${WEB_PORT} (остановить: Ctrl+C)"
  exec python admin.py
fi

# admin в фоне (лог в bot_data/admin.log), бот — в терминале
mkdir -p bot_data
echo "→ Запускаю веб-админ-панель в фоне: http://localhost:${WEB_PORT} (лог: bot_data/admin.log)"
nohup python admin.py >> bot_data/admin.out 2>&1 &
echo "   (остановить админку:  pkill -f 'python admin.py')"
sleep 2

echo "→ Запускаю бота (остановить: Ctrl+C)"
exec python bot.py
