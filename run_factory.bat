@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден в PATH. Укажите путь в этой строке:
  echo set PY=C:\Python311\python.exe
  pause
  exit /b 1
)
python run_factory.py
pause
