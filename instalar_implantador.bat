@echo off
chcp 65001 >nul
REM Instala o implantador automatico do SiRG (Git) neste computador. Rode UMA vez, como administrador.
REM Coloque este arquivo na pasta "Relatorio de Gestao" (a que tem a pasta producao) ou rode de dentro do codigo.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "AQUI=%~dp0"
set "RAIZ=%~dp0"
if exist "%AQUI%manage.py" for %%i in ("%AQUI%..\..") do set "RAIZ=%%~fi\"
if exist "%AQUI%implantacao\git\implantador.ps1" (set "ORIGEM=%AQUI%implantacao\git") else (set "ORIGEM=%AQUI%")
powershell -NoProfile -ExecutionPolicy Bypass -File "%ORIGEM%\instalar_implantador.ps1" -Raiz "%RAIZ:~0,-1%" -Origem "%ORIGEM%"
echo.
pause
