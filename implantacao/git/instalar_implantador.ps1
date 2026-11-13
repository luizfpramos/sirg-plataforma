# Instala (uma vez) o implantador automatico do SiRG neste computador. Chamado pelo instalar_implantador.bat.
# Este arquivo e so ASCII de proposito.
param([Parameter(Mandatory = $true)][string]$Raiz, [Parameter(Mandatory = $true)][string]$Origem)
$ErrorActionPreference = "Stop"
$Base = "C:\ProgramData\SiRG\implantador"
$Tarefa = "SiRG - Implantador"
function Titulo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }

Titulo "1) Conferindo o Git"
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "O Git nao esta instalado. Instale o Git for Windows (https://git-scm.com/download/win)," -ForegroundColor Red
    Write-Host "com as opcoes padrao, e rode este instalador de novo." -ForegroundColor Red
    exit 1
}
Write-Host "   $(git --version)"
if (-not (Test-Path (Join-Path $Raiz "producao\sirg-plataforma\manage.py"))) {
    Write-Host "Nao achei a producao em $Raiz\producao\sirg-plataforma." -ForegroundColor Red; exit 1
}

Titulo "2) Pasta do implantador: $Base"
New-Item -ItemType Directory -Force -Path $Base | Out-Null
Copy-Item (Join-Path $Origem "implantador.ps1") $Base -Force
# so administradores e o sistema leem esta pasta (tem a chave de acesso ao GitHub)
& icacls $Base /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null

Titulo "3) Endereco do repositorio"
$cfgArq = Join-Path $Base "config.json"
$atual = ""
if (Test-Path $cfgArq) { $atual = (Get-Content $cfgArq -Raw -Encoding UTF8 | ConvertFrom-Json).repositorio }
$rep = Read-Host "   Endereco SSH do repositorio (ex.: git@github.com:usuario/sirg-plataforma.git)$(if ($atual) { " [Enter = $atual]" })"
if (-not $rep) { $rep = $atual }
if ($rep -notmatch '^git@github\.com:[\w.-]+/[\w.-]+(\.git)?$') { Write-Host "Endereco invalido. Use o endereco SSH (Code > SSH no GitHub)." -ForegroundColor Red; exit 1 }
[pscustomobject]@{ repositorio = $rep; raiz = $Raiz } | ConvertTo-Json | Set-Content -Path $cfgArq -Encoding UTF8

Titulo "4) Chave de leitura do GitHub (deploy key)"
$chave = Join-Path $Base "chave_github"
if (-not (Test-Path $chave)) {
    $kg = (Get-Command ssh-keygen -ErrorAction SilentlyContinue).Source
    if (-not $kg) { $kg = Join-Path (Split-Path (Split-Path $git.Source)) "usr\bin\ssh-keygen.exe" }
    Start-Process -FilePath $kg -ArgumentList "-t ed25519 -q -N `"`" -C sirg-implantador -f `"$chave`"" -Wait -NoNewWindow
}
Write-Host ""
Write-Host "   Copie a linha abaixo e cadastre no GitHub:" -ForegroundColor Yellow
Write-Host "   repositorio > Settings > Deploy keys > Add deploy key" -ForegroundColor Yellow
Write-Host "   Titulo: SiRG implantador (PC da DGDI). NAO marque 'Allow write access'." -ForegroundColor Yellow
Write-Host ""
Write-Host (Get-Content "$chave.pub")
Write-Host ""
Read-Host "   Depois de cadastrar, aperte Enter para testar" | Out-Null
$k = ($Base -replace '\\', '/')
$env:GIT_SSH_COMMAND = "ssh -i `"$k/chave_github`" -o IdentitiesOnly=yes -o UserKnownHostsFile=`"$k/known_hosts`" -o StrictHostKeyChecking=accept-new"
$ErrorActionPreference = "Continue"
# o aviso do SSH na primeira conexao ("Permanently added ... known hosts") vai para o canal de erro e o
# PowerShell 5 mostraria em vermelho como se fosse erro: so a resposta do GitHub aparece
$resposta = & git ls-remote $rep "refs/heads/main" 2>$null
if ($resposta) { Write-Host "   $resposta" }
if ($LASTEXITCODE -ne 0) { Write-Host "Nao consegui ler o repositorio. Confira a deploy key e o endereco e rode de novo." -ForegroundColor Red; exit 1 }
Write-Host "   ok: o repositorio pode ser lido." -ForegroundColor Green
$ErrorActionPreference = "Stop"

Titulo "5) Estado inicial"
# o que esta instalado hoje fica como esta: o implantador so age quando o GitHub tiver codigo novo
$estado = Join-Path $Base "estado.json"
if (-not (Test-Path $estado)) {
    $hmlAtual = ""; $prdAtual = ""
    $r = Read-Host "   Considerar que a homologacao e a producao ja estao com o codigo atual do ramo implantar/hml e implantar/prd? (S/N, Enter = S)"
    if ($r -notmatch '^[nN]') {
        $hmlAtual = (& git ls-remote $rep "refs/heads/implantar/hml" 2>$null) -split "\s" | Select-Object -First 1
        $prdAtual = (& git ls-remote $rep "refs/heads/implantar/prd" 2>$null) -split "\s" | Select-Object -First 1
    }
    [pscustomobject]@{ hml = "$hmlAtual"; prd = "$prdAtual"; hml_falhou = ""; prd_falhou = "" } | ConvertTo-Json | Set-Content $estado -Encoding UTF8
}

Titulo "6) Tarefa agendada '$Tarefa' (a cada 5 minutos)"
$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Base\implantador.ps1`"" -WorkingDirectory $Base
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$conf = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$quem = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $Tarefa -Action $acao -Trigger $gatilho -Settings $conf -Principal $quem -Force | Out-Null
Write-Host "   ok" -ForegroundColor Green
Write-Host ""
Write-Host "Pronto. O implantador confere o GitHub a cada 5 minutos." -ForegroundColor Green
Write-Host "   Log: $Base\logs"
Write-Host "   Pausar: Agendador de Tarefas > '$Tarefa' > Desabilitar."
Write-Host "   Os instalar_hml.bat e subir_prd.bat continuam funcionando, como plano B."
