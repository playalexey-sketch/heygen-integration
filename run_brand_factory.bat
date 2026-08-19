@echo off
REM Brand Factory OS — самозапускающийся bat для Windows
REM Двойной клик по файлу

set PORT=8002
echo [BrandFactory] Проверка Python...
python --version
if %errorlevel% neq 0 (
  echo Python не найден, поставь Python 3.10+ с python.org
  pause
  exit /b
)

echo [BrandFactory] Ставлю зависимости...
python -m pip install -q fastapi uvicorn[standard] pydantic python-multipart

echo [BrandFactory] Стартуем Brand Factory OS на http://localhost:%PORT%
echo [BrandFactory] Пример: brand_factory\projects\demo_example\artifacts\07_brand_manifest.md
echo [BrandFactory] Доку: brand_factory\docs\ANALYSIS_FULL.md
echo.

python -m brand_factory.server

pause
