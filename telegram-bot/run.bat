@echo off
rem Одной командой: зависимости + запуск бота (Windows)
rem
rem   run.bat
rem
rem Первый раз создаст venv, поставит зависимости, создаст .env из шаблона.
cd /d %~dp0

where python >nul 2>nul
if %errorlevel% neq 0 (
  echo Не найден Python. Установите Python 3.10+ ^(https://www.python.org/downloads/^)
  echo и при установке отметьте галку "Add Python to PATH".
  pause
  exit /b 1
)

if not exist venv (
  echo - Создаю виртуальное окружение ^(venv^)...
  python -m venv venv
)

call venv\Scripts\activate.bat

echo - Проверяю зависимости...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if not exist .env (
  copy .env.example .env >nul
  echo.
  echo Я создал файл .env из шаблона.
  echo Впишите в него BOT_TOKEN и ADMIN_ID, затем запустите run.bat ещё раз.
  echo   Токен бота:      @BotFather  -\> /newbot (или /token)
  echo   Ваш Telegram ID: напишите боту @userinfobot
  pause
  exit /b 0
)

echo - Запускаю бота ^(остановить: Ctrl+C^)...
python main.py
pause
