@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Rode instalar.bat primeiro. & pause & exit /b 1)
.venv\Scripts\python.exe manage.py migrate --noinput || goto erro
.venv\Scripts\python.exe manage.py collectstatic --noinput >nul || goto erro
echo Servidor de rede da Plataforma SiRG (porta definida em SIRG_PORTA no .env; padrao 8001). Ctrl+C para parar.
.venv\Scripts\python.exe servir.py
:erro
if /i "%~1"=="tarefa" exit /b 1
echo.
echo O servidor parou. Se apareceu um erro acima, tire um print desta janela e envie.
echo (Se o erro fala em porta/endereco em uso, o SiRG ja esta rodando em outra janela ou na tarefa agendada.)
pause
