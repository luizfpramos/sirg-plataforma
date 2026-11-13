@echo off
chcp 65001 >nul
setlocal
REM Leva para a PRODUCAO (pasta producao\sirg-plataforma) a versao do zip mais novo, com backup antes.
REM Basta deixar o zip da versao (sirg-plataforma-vX.Y.zip) nesta pasta ou em Downloads: nao precisa extrair.
REM A parte depois de "#INICIO_PS" (no fim deste arquivo) e PowerShell; o cmd nunca chega nela.
net session >nul 2>&1
if errorlevel 1 (
  echo Pedindo permissao de administrador...
  set "SIRG_BAT=%~f0"
  powershell -NoProfile -Command "Start-Process -FilePath $env:SIRG_BAT -Verb RunAs"
  exit /b 0
)
title SiRG - subir para producao
set "SIRG_AQUI=%~dp0"
set "SIRG_ALVO=prd"
set "SIRG_BAT=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:SIRG_BAT); Invoke-Expression $t.Substring($t.LastIndexOf('#INICIO_PS'))"
if errorlevel 1 (echo. & echo Algo deu errado. Tire um print desta janela e envie.)
echo.
pause
exit /b
#INICIO_PS
# Acha o zip mais novo do SiRG, extrai numa pasta temporaria e roda o implantar.ps1 que vem dentro dele.
$ErrorActionPreference = "Continue"
$aqui = $env:SIRG_AQUI.TrimEnd('\')
$alvo = $env:SIRG_ALVO
$raiz = $aqui
if ((Split-Path $raiz -Leaf) -eq 'sirg-plataforma') { $raiz = Split-Path $raiz -Parent }
if (@('producao', 'hml') -contains (Split-Path $raiz -Leaf)) { $raiz = Split-Path $raiz -Parent }
$perfil = [Environment]::GetFolderPath('UserProfile')
$lugares = @($aqui, $raiz, (Join-Path $raiz 'producao'), (Join-Path $raiz 'hml'), (Join-Path $perfil 'Downloads'),
             [Environment]::GetFolderPath('Desktop')) | Select-Object -Unique
$melhor = $null; $vmax = $null
foreach ($l in $lugares) {
    if (-not (Test-Path $l)) { continue }
    foreach ($z in @(Get-ChildItem -Path $l -Filter 'sirg-plataforma-v*.zip' -File -ErrorAction SilentlyContinue)) {
        if ($z.Name -match 'sirg-plataforma-v(\d+)\.(\d+)(?:\.(\d+))?') {
            $terc = '0'; if ($Matches[3]) { $terc = $Matches[3] }
            $v = [version]("{0}.{1}.{2}" -f $Matches[1], $Matches[2], $terc)
            if (-not $vmax -or $v -gt $vmax -or ($v -eq $vmax -and $z.LastWriteTime -gt $melhor.LastWriteTime)) { $vmax = $v; $melhor = $z }
        }
    }
}
if (-not $melhor) {
    Write-Host "Nao achei nenhum arquivo sirg-plataforma-vX.Y.zip." -ForegroundColor Red
    Write-Host "Coloque o zip da versao em $raiz (ou deixe na pasta Downloads) e rode de novo."
    exit 1
}
Write-Host "Pasta do Relatorio de Gestao: $raiz"
Write-Host "Versao encontrada:            $($melhor.FullName)"
$tmp = Join-Path $env:TEMP ('sirg-implantar-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
Write-Host "Extraindo o zip..."
try { Expand-Archive -LiteralPath $melhor.FullName -DestinationPath $tmp -Force -ErrorAction Stop }
catch { Write-Host "Nao foi possivel abrir o zip: $_" -ForegroundColor Red; exit 1 }
$origem = Join-Path $tmp 'sirg-plataforma'
if (-not (Test-Path (Join-Path $origem 'manage.py'))) {
    $d = Get-ChildItem $tmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'manage.py') } | Select-Object -First 1
    if ($d) { $origem = $d.FullName }
}
$script = Join-Path $origem 'implantacao\implantar.ps1'
if (-not (Test-Path $script)) { Write-Host "Este zip nao traz o implantar.ps1 (use a versao 2.12 ou mais nova)." -ForegroundColor Red; exit 1 }
$codigo = 0
try { & $script -Alvo $alvo -Origem $origem -Raiz $raiz -Zip $melhor.FullName } catch { $codigo = 1 }
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
exit $codigo
