@echo off
setlocal
cd /d %~dp0
title TG BOT

echo ==================================================
echo  Работаем в папке: %CD%
echo  Если это не ваша папка telegram-bot - вы
echo  запустили run.bat не оттуда.
echo ==================================================
echo.

echo [1/4] Проверка Python:
where python >nul 2>nul
if %errorlevel% neq 0 (
  echo     PYTHON NOT FOUND.
  echo     Установите Python 3.10+: https://www.python.org/downloads/
  echo     ВАЖНО: отметьте галочку "Add Python to PATH".
  goto :finish
)
echo     найден

if not exist venv\Scripts\python.exe (
  echo [2/4] Создаю venv, может занять минуту...
  python -m venv venv
  if not exist venv\Scripts\python.exe (
    echo     VENV FAILED.
    echo     Если открылось окно Microsoft Store - ваш "python"
    echo     это заглушка из магазина, а не настоящий Python.
    echo     Установите с https://www.python.org/downloads/
    echo     и отметьте галочку "Add Python to PATH".
    goto :finish
  )
  echo     OK
) else (
  echo [2/4] venv: OK
)
call venv\Scripts\activate.bat

echo [3/4] Зависимости, может занять несколько минут...
python -m pip install -q --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
  echo     PIP FAILED - ошибки выше.
  goto :finish
)
echo     OK

if not exist .env (
  copy .env.example .env >nul
  echo [4/4] Создал .env из шаблона.
) else (
  echo [4/4] .env: есть.
)
findstr /C:"PASTE_YOUR_BOT_TOKEN" .env >nul
if %errorlevel% equ 0 (
  echo     BOT_TOKEN ещё не вписан.
  echo     Выполните:  notepad .env
  echo     Впишите BOT_TOKEN и ADMIN_ID, сохраните,
  echo     и ЗАПУСТИТЕ run.bat ЕЩЁ РАЗ - бот поднимется только тогда.
  goto :finish
)

echo.
echo [5/5] Запускаю бота, остановить: Ctrl+C
echo ------------------------------------------------------------
python main.py
echo ------------------------------------------------------------
echo     Бот остановлен.
goto :finish

:finish
echo.
echo Окно закроется само через 20 секунд.
timeout /t 20 >nul
