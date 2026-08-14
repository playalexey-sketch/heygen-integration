@echo off
chcp 65001 >nul
title HeyGen Студия
cd /d "%~dp0"
echo.
echo   Запускаю HeyGen Студию...
echo.
where python >nul 2>nul
if %errorlevel%==0 ( python start.py & goto :end )
where py >nul 2>nul
if %errorlevel%==0 ( py start.py & goto :end )
echo   [!] Python не найден.
echo   Установите его с https://www.python.org/downloads/
echo   и отметьте галочку "Add Python to PATH".
pause
:end
pause
