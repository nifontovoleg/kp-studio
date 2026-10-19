@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Сначала запустите setup.ps1 по инструкции README.md
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m studio.web --open
pause
