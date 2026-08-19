@echo off
setlocal
cd /d %~dp0
title TG BOT

echo ==================================================
echo  Working folder: %CD%
echo  If this is not your telegram-bot folder, you
echo  launched run.bat from the wrong place.
echo ==================================================
echo.

echo [1/4] Checking Python:
where python >nul 2>nul
if %errorlevel% neq 0 (
  echo     PYTHON NOT FOUND.
  echo     Install Python 3.10+: https://www.python.org/downloads/
  echo     IMPORTANT: check the box "Add Python to PATH".
  goto :stay_open
)
echo     found

if not exist venv\Scripts\python.exe (
  echo [2/4] Creating venv, may take a minute...
  python -m venv venv
  if not exist venv\Scripts\python.exe (
    echo     VENV FAILED.
    echo     If a Microsoft Store window opened, your "python"
    echo     is a store stub, not real Python.
    echo     Install from https://www.python.org/downloads/
    echo     and check the box "Add Python to PATH".
    goto :stay_open
  )
  echo     OK
) else (
  echo [2/4] venv: OK
)
call venv\Scripts\activate.bat

echo [3/4] Installing dependencies, may take a few minutes...
python -m pip install -q --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
  echo     PIP FAILED - see errors above.
  goto :stay_open
)
echo     OK

if not exist .env (
  copy .env.example .env >nul
  echo [4/4] Created .env from template.
) else (
  echo [4/4] .env: present.
)
findstr /C:"PASTE_YOUR_BOT_TOKEN" .env >nul
if %errorlevel% equ 0 (
  echo     BOT_TOKEN is not filled in yet.
  echo     Run:  notepad .env
  echo     Fill in BOT_TOKEN and ADMIN_ID, save,
  echo     then RUN run.bat AGAIN - the bot starts only then.
  goto :stay_open
)

echo.
echo [5/5] Starting bot and web panel, stop with Ctrl+C
echo     Web panel: http://localhost:8080
echo ------------------------------------------------------------
python main.py
set "EC=%errorlevel%"
echo ------------------------------------------------------------
if "%EC%"=="0" (
  echo     Bot stopped by user. The window closes in 30 seconds.
  goto :auto_close
)
echo.
echo  !!! BOT CRASHED, exit code %EC% !!!
echo  Full error details are saved in the file:  bot_data\bot.log
echo  Open it:  notepad bot_data\bot.log
echo  The window stays open - send me the last lines of the log.
goto :stay_open

:stay_open
echo.
echo The window stays open for 5 minutes, then closes.
timeout /t 300 >nul
goto :end

:auto_close
echo.
timeout /t 30 >nul
goto :end

:end
exit /b
