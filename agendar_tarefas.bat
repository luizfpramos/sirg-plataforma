@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM Precisa ser executado como ADMINISTRADOR (botao direito > Executar como administrador)
net session >nul 2>&1 || (echo Execute este arquivo como ADMINISTRADOR: botao direito ^> Executar como administrador. & pause & exit /b 1)
set PORTA=8001
for /f "tokens=1,* delims==" %%a in ('findstr /b /c:"SIRG_PORTA=" .env 2^>nul') do set PORTA=%%b
set PASTA=%~dp0
echo.
echo 1) Servidor do SiRG ao ligar o Windows (mesmo sem ninguem logado), sem limite de tempo
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $a=New-ScheduledTaskAction -Execute '%PASTA%servidor.bat' -Argument 'tarefa' -WorkingDirectory '%PASTA%'; $t=New-ScheduledTaskTrigger -AtStartup; $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; $p=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest; Register-ScheduledTask -TaskName 'SiRG - Servidor' -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null" || goto erro
echo    ok
echo.
echo 2) Backup diario as 12:30 e as 19:00
schtasks /Create /TN "SiRG - Backup 12h30" /TR "\"%PASTA%backup.bat\"" /SC DAILY /ST 12:30 /RU SYSTEM /F >nul || goto erro
schtasks /Create /TN "SiRG - Backup 19h" /TR "\"%PASTA%backup.bat\"" /SC DAILY /ST 19:00 /RU SYSTEM /F >nul || goto erro
echo    ok
echo.
echo 3) Liberacao da porta %PORTA% no Firewall do Windows
netsh advfirewall firewall delete rule name="SiRG porta %PORTA%" >nul 2>&1
netsh advfirewall firewall add rule name="SiRG porta %PORTA%" dir=in action=allow protocol=TCP localport=%PORTA% >nul || goto erro
echo    ok
echo.
echo 4) Energia: o computador nao suspende nem hiberna quando ligado na tomada
powercfg /change standby-timeout-ac 0 >nul
powercfg /change hibernate-timeout-ac 0 >nul
echo    ok
echo.
echo 5) Iniciando o servidor agora (sem precisar reiniciar o computador)
schtasks /End /TN "SiRG - Servidor" >nul 2>&1
schtasks /Run /TN "SiRG - Servidor" >nul || goto erro
timeout /t 15 /nobreak >nul
netstat -ano | findstr /R /C:"0.0.0.0:%PORTA% .*LISTENING" >nul && (echo    ok: o SiRG esta no ar na porta %PORTA%.) || (echo    O servidor ainda nao respondeu. Aguarde um minuto e abra http://127.0.0.1:8001 neste computador.)
echo.
echo Pronto.
echo Para remover tudo depois: remover_tarefas.bat (como administrador)
pause
exit /b 0
:erro
echo Ocorreu um erro. Confira se este arquivo foi executado como administrador.
pause
exit /b 1
