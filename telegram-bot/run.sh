#!/usr/bin/env bash
# Одной командой: зависимости + запуск бота (Linux / macOS)
#
#   ./run.sh
#
# Первый раз создаст venv, поставит зависимости, создаст .env из шаблона.
# Далее — просто ./run.sh (бот запустится, остановить — Ctrl+C).
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
  echo "Впишите в него BOT_TOKEN (и ADMIN_ID) и запустите ./run.sh ещё раз."
  echo "  Токен бота:  @BotFather  → /newbot (или /token)"
  echo "  Ваш Telegram ID: напишите боту @userinfobot"
  exit 0
fi

if grep -q "PASTE_YOUR_BOT_TOKEN" .env; then
  echo
  echo "В .env ещё не вписан BOT_TOKEN. Впишите его в файл .env и запустите ./run.sh ещё раз."
  exit 1
fi

# --- 4. запуск ---
echo "→ Запускаю бота (остановить: Ctrl+C)…"
exec python main.py
