@echo off
REM ============================================================
REM  Установка Hermes (локальный чат) — Windows
REM  Ставит Ollama, скачивает модель hermes3:8b и запускает чат.
REM  Просто дважды кликните.
REM ============================================================
cd /d "%~dp0"

echo ==============================================
echo  Установка локального чата Hermes (NousResearch)
echo ==============================================
echo.

REM 1. Проверяем/ставим Ollama
where ollama >nul 2>nul
if errorlevel 1 (
    echo [1/4] Ollama не найден. Скачиваю установщик Ollama...
    powershell -Command "Invoke-WebRequest -Uri https://ollama.com/download/OllamaSetup.exe -OutFile %TEMP%\OllamaSetup.exe"
    echo Установите Ollama (согласитесь) и затем запустите этот файл ещё раз.
    start %TEMP%\OllamaSetup.exe
    exit /b 0
)

echo [1/4] Ollama найден.

REM 2. Скачиваем модель (по умолчанию hermes3:8b ~4.7 ГБ)
set MODEL=hermes3:8b
if not "%~1"=="" set MODEL=%~1
echo [2/4] Скачиваю модель %MODEL% (первый раз может занять время)...
ollama pull %MODEL%
if errorlevel 1 (
    echo [ОШИБКА] Не удалось скачать модель. Проверьте интернет и запустите Ollama.
    pause
    exit /b 1
)

echo [3/4] Устанавливаю Python-зависимости...
pip install -q fastapi uvicorn requests python-multipart

echo [4/4] Запускаю чат. Откройте в браузере: http://localhost:8002
echo.

python run_hermes.py

pause
