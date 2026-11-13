@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM Para o servidor, atualiza e liga de novo. Precisa de administrador (o servidor roda como tarefa do sistema):
REM se nao estiver como administrador, pede a permissao e abre de novo.
net session >nul 2>&1
if errorlevel 1 (
  echo Pedindo permissao de administrador para parar e ligar o servidor...
  set "SIRG_BAT=%~f0"
  powershell -NoProfile -Command "Start-Process -FilePath $env:SIRG_BAT -Verb RunAs"
  exit /b 0
)
if not exist .venv\Scripts\python.exe (echo Rode instalar.bat primeiro. & pause & exit /b 1)
set "SIRG_PS=%~dp0servico.ps1"
echo Atualizando a Plataforma SiRG (os usuarios e dados da pasta "dados" sao mantidos)...
echo.
echo 1) Parando o servidor
powershell -NoProfile -ExecutionPolicy Bypass -Command "& $env:SIRG_PS parar"
echo.
echo 2) Atualizando
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto erro
.venv\Scripts\python.exe manage.py migrate --noinput || goto erro
.venv\Scripts\python.exe manage.py inicializar || goto erro
.venv\Scripts\python.exe manage.py collectstatic --noinput || goto erro
.venv\Scripts\python.exe manage.py preparar_rg2026 --sem-backup || goto erro
echo.
echo 3) Ligando o servidor de novo
powershell -NoProfile -ExecutionPolicy Bypass -Command "& $env:SIRG_PS ligar"
echo.
echo Atualizacao concluida. Abra o site e aperte Ctrl+F5 para carregar a versao nova.
pause
exit /b 0
:erro
echo.
echo ERRO na atualizacao. Tire um print desta janela e envie.
echo Ligando o servidor de novo...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& $env:SIRG_PS ligar"
pause
exit /b 1
