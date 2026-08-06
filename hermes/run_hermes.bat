@echo off
REM ============================================================
REM  Запуск локального чата Hermes — Windows
REM  (модель уже должна быть скачана: install_hermes.bat)
REM ============================================================
cd /d "%~dp0"

echo Запускаю чат Hermes...
echo Откройте в браузере:  http://localhost:8002
echo Нажмите Ctrl+C, чтобы остановить.
echo.

python run_hermes.py

pause
