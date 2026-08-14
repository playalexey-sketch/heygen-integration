#!/usr/bin/env bash
# Запуск веб-панели агента Timeweb Cloud (Linux / macOS).
set -e
cd "$(dirname "$0")"

echo
echo "============================================="
echo "  Timeweb Агент - запуск веб-панели"
echo "============================================="
echo

# 1. виртуальное окружение
if [ ! -d venv ]; then
  echo "[1/3] Создаю виртуальное окружение venv..."
  python3 -m venv venv
fi
source venv/bin/activate

# 2. зависимости
echo "[2/3] Устанавливаю зависимости..."
pip install -q --upgrade pip
pip install -q -r timeweb_agent/requirements.txt

# 3. файл .env
if [ ! -f .env ]; then
  cp timeweb_agent/.env.example .env
  echo
  echo "Создан файл .env — отредактируйте его (токен Timeweb, SSH к VPS)"
  echo "и запустите этот скрипт ещё раз."
  exit 0
fi

# 4. запуск
echo "[3/3] Запускаю веб-панель... (браузер откроется автоматически)"
python -m timeweb_agent web
