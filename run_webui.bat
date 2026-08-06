@echo off
REM ============================================================
REM  Запуск веб-интерфейса LTX-2 (фото -> видео с аватаром)
REM  Просто дважды кликните по этому файлу.
REM ============================================================
cd /d "%~dp0"

REM Укажите путь к вашему python, если он не в PATH.
REM Например:  set PY= C:\Python310\python.exe
set PY=python

where %PY% >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден в PATH.
    echo Укажите путь вручную: откройте этот .bat и поменяйте  set PY=
    pause
    exit /b 1
)

echo Запускаю веб-интерфейс LTX-2...
echo Откройте в браузере:  http://localhost:8001
echo Нажмите Ctrl+C, чтобы остановить сервер.
echo.

%PY% run_webui.py

pause
