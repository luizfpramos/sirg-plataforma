@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat || (echo Rode instalar.bat primeiro. & pause & exit /b 1)
python manage.py migrate --noinput >nul
python manage.py collectstatic --noinput >nul
echo Plataforma SiRG em http://127.0.0.1:8001  (Ctrl+C para parar)
start "" http://127.0.0.1:8001
python manage.py runserver --insecure 127.0.0.1:8001
