@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat || (echo Rode instalar.bat primeiro. & exit /b 1)
python manage.py backup >> dados\backup.log 2>&1
