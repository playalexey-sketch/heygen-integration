@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  =============================================
echo   Timeweb Агент - запуск веб-панели
echo  =============================================
echo.

rem --- определяем python ---
where python >nul 2>nul
if %errorlevel%==0 (set "PY=python") else (set "PY=py -3")

rem --- 1. виртуальное окружение ---
if not exist "venv\Scripts\python.exe" (
    echo [1/3] Создаю виртуальное окружение venv...
    %PY% -m venv venv
    if errorlevel 1 (
        echo.
        echo ОШИБКА: не удалось создать venv. Установите Python 3.9+ с python.org
        echo и отметьте галочку "Add Python to PATH" при установке.
        pause
        exit /b 1
    )
)

echo [2/3] Устанавливаю зависимости...
"venv\Scripts\python.exe" -m pip install -q --upgrade pip
"venv\Scripts\python.exe" -m pip install -q -r timeweb_agent\requirements.txt
if errorlevel 1 (
    echo ОШИБКА при установке зависимостей. Проверьте интернет-соединение.
    pause
    exit /b 1
)

rem --- 2. файл .env ---
if not exist ".env" (
    echo.
    echo Файл .env не найден - создаю из шаблона...
    copy /y timeweb_agent\.env.example .env >nul
    echo.
    echo  ВАЖНО: сейчас откроется файл .env. Заполните его:
    echo   1. TIMEWEB_CLOUD_TOKEN - токен из https://timeweb.cloud/my/api-keys
    echo   2. TW_SSH_HOST + TW_SSH_PASSWORD - доступ к вашему VPS
    echo  Затем сохраните файл и запустите этот скрипт ещё раз.
    echo.
    start notepad .env
    pause
    exit /b 0
)

rem --- 3. запуск ---
echo [3/3] Запускаю веб-панель... (браузер откроется автоматически)
"venv\Scripts\python.exe" -m timeweb_agent web
pause
