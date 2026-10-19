@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo API requests use your provider balance.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
