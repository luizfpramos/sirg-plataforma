@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo === Plataforma SiRG - instalacao ===
echo.
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version || (echo Python nao encontrado. Instale o Python 3.11+ de python.org marcando "Add python.exe to PATH". & pause & exit /b 1)
if not exist .venv (
  echo Criando ambiente virtual .venv ...
  %PY% -m venv .venv || (echo Falha ao criar o ambiente virtual. & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (echo Falha ao instalar as dependencias. Verifique a conexao com a internet/proxy. & pause & exit /b 1)
if not exist .env copy .env.exemplo .env >nul
python manage.py migrate || (pause & exit /b 1)
python manage.py collectstatic --noinput >nul
python manage.py inicializar || (pause & exit /b 1)
echo Preparando o Relatorio de Gestao 2026 (com o historico do RG 2025 publicado)...
python manage.py preparar_rg2026 || (pause & exit /b 1)
echo.
echo === Crie agora o ADMINISTRADOR da plataforma (login e senha) ===
python manage.py criar_admin || (pause & exit /b 1)
echo.
echo Instalacao concluida.
echo  - Para testar so neste computador: iniciar.bat  (http://127.0.0.1:8001)
echo  - Para os colegas acessarem pela rede: servidor.bat  (confira o arquivo .env)
echo  - Para iniciar sozinho com o Windows e fazer backup diario: agendar_tarefas.bat (como administrador)
pause
