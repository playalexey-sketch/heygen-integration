@echo off
chcp 65001 >nul
title HeyGen Студия - тестовый режим
cd /d "%~dp0"
echo.
echo   Тестовый режим: кредиты HeyGen не расходуются.
echo.
where python >nul 2>nul
if %errorlevel%==0 ( python start.py --test & goto :end )
where py >nul 2>nul
if %errorlevel%==0 ( py start.py --test & goto :end )
echo   [!] Python не найден.
pause
:end
pause
