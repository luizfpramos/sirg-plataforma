@echo off
chcp 65001 >nul
net session >nul 2>&1 || (echo Execute este arquivo como ADMINISTRADOR. & pause & exit /b 1)
schtasks /End /TN "SiRG - Servidor" >nul 2>&1
schtasks /Delete /TN "SiRG - Servidor" /F
schtasks /Delete /TN "SiRG - Backup 12h30" /F
schtasks /Delete /TN "SiRG - Backup 19h" /F
echo Tarefas removidas. (A regra do firewall "SiRG porta ..." continua; remova pelo Firewall do Windows se quiser.)
pause
