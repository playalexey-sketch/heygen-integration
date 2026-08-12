@echo off
REM Запуск движка модели для OpenClaw без Ollama (llama.cpp). Windows.
REM
REM 1) Скачайте llama-<версия>-bin-win-cuda-x64.zip (NVIDIA)
REM    или llama-<версия>-bin-win-cpu-x64.zip (без видеокарты)
REM    с https://github.com/ggml-org/llama.cpp/releases
REM 2) Распакуйте, например, в C:\llama
REM 3) Пропишите путь в LLAMA_DIR ниже (или добавьте папку в PATH)
REM 4) Запустите этот файл двойным кликом

setlocal

REM ---- Настройки ---------------------------------------------------------
set "LLAMA_DIR=C:\llama"

REM Модель под объём RAM/VRAM:
REM   8 ГБ    unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M
REM   16 ГБ   unsloth/Qwen3-8B-GGUF:Q4_K_M          <- по умолчанию
REM   24-32   unsloth/Qwen3-14B-GGUF:Q4_K_M
REM   32+     unsloth/gpt-oss-20b-GGUF:Q4_K_M
set "MODEL=unsloth/Qwen3-8B-GGUF:Q4_K_M"

set "PORT=8080"
set "HOST=127.0.0.1"
set "CTX=32768"
set "ALIAS=local-model"
set "NGL=99"

REM ---- Проверка ----------------------------------------------------------
if exist "%LLAMA_DIR%\llama-server.exe" (
    set "LLAMA_BIN=%LLAMA_DIR%\llama-server.exe"
) else (
    where llama-server.exe >nul 2>&1
    if errorlevel 1 (
        echo ОШИБКА: llama-server.exe не найден.
        echo Проверьте путь LLAMA_DIR в этом файле: %LLAMA_DIR%
        echo Скачать: https://github.com/ggml-org/llama.cpp/releases
        pause
        exit /b 1
    )
    set "LLAMA_BIN=llama-server.exe"
)

REM ---- Запуск ------------------------------------------------------------
echo Модель:    %MODEL%
echo Адрес:     http://%HOST%:%PORT%/v1
echo Контекст:  %CTX%
echo ID модели: %ALIAS%   (это же значение - в openclaw.json)
echo.
echo Первый запуск скачивает модель, это может занять несколько минут.
echo Не закрывайте это окно, пока пользуетесь ботом.
echo.

REM --jinja ОБЯЗАТЕЛЕН: без него не работает tool calling.
"%LLAMA_BIN%" -hf %MODEL% --jinja -c %CTX% -ngl %NGL% --host %HOST% --port %PORT% --alias %ALIAS%

pause
