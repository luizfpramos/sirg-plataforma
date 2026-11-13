# Implantacao do SiRG: homologacao (HML) e producao (PRD).
#
# Chamado pelo instalar_hml.bat e pelo subir_prd.bat, a partir da pasta ja extraida do zip da versao.
#   -Alvo hml : instala ou atualiza a homologacao em <Raiz>\hml\sirg-plataforma (porta 8003, tarefa "SiRG - HML")
#   -Alvo prd : atualiza a producao em <Raiz>\producao\sirg-plataforma (porta do .env, tarefa "SiRG - Servidor"),
#               com backup dos dados e copia do codigo anterior em <Raiz>\versoes_anteriores
#
# O que nunca e tocado: a pasta "dados" (banco, arquivos enviados, chave), o arquivo .env e a .venv.
# Este arquivo e so ASCII de proposito (o PowerShell 5 do Windows le scripts sem BOM como ANSI).
param(
    [Parameter(Mandatory = $true)][ValidateSet("hml", "prd")][string]$Alvo,
    [Parameter(Mandatory = $true)][string]$Origem,
    [Parameter(Mandatory = $true)][string]$Raiz,
    [string]$Zip = "",
    # chamado pelo implantador automatico (Git): nao pergunta nada; mantem os dados da homologacao
    [switch]$Automatico,
    [switch]$CopiarDados
)
# "Continue": no PowerShell 5, avisos que programas como o pip escrevem no canal de erro virariam falha.
# Cada etapa confere o codigo de saida ($LASTEXITCODE) e os comandos criticos usam -ErrorAction Stop.
$ErrorActionPreference = "Continue"
$Origem = $Origem.TrimEnd("\")
$Raiz = $Raiz.TrimEnd("\")
$PRD = Join-Path $Raiz "producao\sirg-plataforma"
$HML = Join-Path $Raiz "hml\sirg-plataforma"
# um nivel so abaixo de softwares.net.br: o certificado gratuito do Cloudflare (*.softwares.net.br) nao cobre
# hml.sirg.softwares.net.br (dois niveis), que da ERR_SSL_VERSION_OR_CIPHER_MISMATCH
$HML_HOST = "hml-sirg.softwares.net.br"
$HML_PORTA = 8003
$HML_TAREFA = "SiRG - HML"

function Titulo($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   $t" -ForegroundColor Yellow }
function Falhar($t) { Write-Host ""; Write-Host "ERRO: $t" -ForegroundColor Red; throw $t }

function Versao($pasta) {
    $s = Join-Path $pasta "config\settings.py"
    if (-not (Test-Path $s)) { return "" }
    foreach ($l in Get-Content $s) { if ($l -match '^\s*SIRG_VERSAO\s*=\s*"([^"]+)"') { return $Matches[1] } }
    return ""
}

function LerEnv($pasta, $chave, $padrao) {
    $f = Join-Path $pasta ".env"
    if (Test-Path $f) {
        foreach ($l in Get-Content $f -Encoding UTF8) {
            if ($l -match ('^\s*' + [regex]::Escape($chave) + '\s*=\s*(.*)$')) { return $Matches[1].Trim().Trim('"') }
        }
    }
    return $padrao
}

function GravarEnv($arquivo, $chave, $valor) {
    $linhas = @()
    if (Test-Path $arquivo) { $linhas = @(Get-Content $arquivo -Encoding UTF8) }
    $achou = $false
    $novas = foreach ($l in $linhas) {
        if ($l -match ('^\s*#?\s*' + [regex]::Escape($chave) + '\s*=')) {
            if (-not $achou) { $achou = $true; "$chave=$valor" }
        } else { $l }
    }
    if (-not $achou) { $novas = @($novas) + "$chave=$valor" }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($arquivo, [string[]]$novas, $utf8)
}

function Python($pasta) { return (Join-Path $pasta ".venv\Scripts\python.exe") }

function Rodar($pasta, [string[]]$argumentos, $rotulo) {
    Push-Location $pasta
    try {
        & (Python $pasta) @argumentos
        if ($LASTEXITCODE -ne 0) { Falhar "$rotulo (codigo $LASTEXITCODE)" }
    } finally { Pop-Location }
}

function Porta($pasta, $padrao) { return [int](LerEnv $pasta "SIRG_PORTA" $padrao) }

function PararServidor($pasta, $tarefa, $porta) {
    schtasks /End /TN $tarefa 2>$null | Out-Null
    $todos = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $alvos = New-Object System.Collections.Generic.HashSet[int]
    $pidArq = Join-Path $pasta "dados\servidor.pid"
    if (Test-Path $pidArq) {
        $n = 0
        if ([int]::TryParse((Get-Content $pidArq -Raw).Trim(), [ref]$n)) {
            $p = Get-Process -Id $n -ErrorAction SilentlyContinue
            if ($p -and $p.ProcessName -like "python*") { [void]$alvos.Add($n) }
        }
    }
    $venv = (Join-Path $pasta ".venv\").ToLower()
    $bat = (Join-Path $pasta "servidor.bat").ToLower()
    foreach ($r in $todos) {
        $cmd = "$($r.CommandLine)".ToLower(); $exe = "$($r.ExecutablePath)".ToLower()
        if (($r.Name -eq "cmd.exe" -and $cmd.Contains($bat)) -or ($exe.Contains($venv) -and $cmd.Contains("servir.py"))) {
            [void]$alvos.Add([int]$r.ProcessId)
        }
    }
    # quem escuta na porta so e parado se for um servidor do SiRG (servir.py); outro programa na porta nunca e tocado
    foreach ($c in @(Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)) {
        $r = $todos | Where-Object { $_.ProcessId -eq $c.OwningProcess } | Select-Object -First 1
        if ($r -and "$($r.CommandLine)".ToLower().Contains("servir.py")) { [void]$alvos.Add([int]$c.OwningProcess) }
    }
    $fila = New-Object System.Collections.Generic.Queue[int]
    foreach ($a in $alvos) { $fila.Enqueue($a) }
    while ($fila.Count -gt 0) {
        $pai = $fila.Dequeue()
        foreach ($f in $todos | Where-Object { $_.ParentProcessId -eq $pai }) {
            if ($alvos.Add([int]$f.ProcessId)) { $fila.Enqueue([int]$f.ProcessId) }
        }
    }
    [void]$alvos.Remove($PID)
    foreach ($a in $alvos) { Stop-Process -Id $a -Force -ErrorAction SilentlyContinue }
    Remove-Item $pidArq -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 20; $i++) {
        if (-not (Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
    Ok "Servidor parado."
}

function PortaDeOutroPrograma($porta) {
    # devolve o nome do programa que escuta na porta, se nao for um servidor do SiRG
    foreach ($c in @(Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)) {
        $r = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $c.OwningProcess) -ErrorAction SilentlyContinue
        if (-not $r -or -not "$($r.CommandLine)".ToLower().Contains("servir.py")) {
            if ($r) { return "$($r.Name) (PID $($c.OwningProcess))" } else { return "PID $($c.OwningProcess)" }
        }
    }
    return $null
}

function RegistrarTarefa($pasta, $tarefa) {
    $acao = New-ScheduledTaskAction -Execute (Join-Path $pasta "servidor.bat") -Argument "tarefa" -WorkingDirectory $pasta
    $gatilho = New-ScheduledTaskTrigger -AtStartup
    $conf = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 `
        -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $quem = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $tarefa -Action $acao -Trigger $gatilho -Settings $conf -Principal $quem -Force -ErrorAction Stop | Out-Null
}

function LigarServidor($pasta, $tarefa, $porta) {
    $existe = $false
    try { Get-ScheduledTask -TaskName $tarefa -ErrorAction Stop | Out-Null; $existe = $true } catch { $existe = $false }
    if (-not $existe) { RegistrarTarefa $pasta $tarefa; Ok "Tarefa agendada '$tarefa' criada (liga junto com o Windows)." }
    schtasks /Run /TN $tarefa | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$porta/entrar/" -UseBasicParsing -TimeoutSec 20
                Ok "Servidor no ar na porta $porta (resposta $($r.StatusCode))."
            } catch { Ok "Servidor ligado na porta $porta." }
            return $true
        }
    }
    Aviso "A tarefa foi iniciada, mas o servidor ainda nao respondeu na porta $porta. Aguarde um minuto e abra o site."
    Aviso "Se nao abrir, rode o servidor.bat da pasta $pasta para ver a mensagem de erro."
    return $false
}

function CopiarCodigo($destino) {
    New-Item -ItemType Directory -Force -Path $destino -ErrorAction Stop | Out-Null
    # /E copia tudo (sem apagar nada do destino); dados, .venv, .env e arquivos gerados ficam de fora
    robocopy $Origem $destino /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP `
        /XD dados .venv staticfiles __pycache__ config_ia /XF .env *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) { Falhar "falha ao copiar os arquivos (robocopy $LASTEXITCODE)" }
    # configuracao da IA: so entra o que ainda nao existe (quem escolheu outro provedor nao perde a escolha)
    robocopy (Join-Path $Origem "config_ia") (Join-Path $destino "config_ia") /E /XC /XN /XO /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Falhar "falha ao copiar config_ia (robocopy $LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
    Ok "Arquivos da versao $(Versao $Origem) copiados para $destino"
}

function GarantirVenv($pasta) {
    if (-not (Test-Path (Python $pasta))) {
        Write-Host "   Criando o ambiente Python (.venv)..."
        Push-Location $pasta
        try {
            $py = Get-Command py -ErrorAction SilentlyContinue
            if ($py) { & py -3 -m venv .venv } else { & python -m venv .venv }
        } finally { Pop-Location }
        if (-not (Test-Path (Python $pasta))) { Falhar "nao foi possivel criar a .venv. Instale o Python 3.11+ (python.org) com 'Add python.exe to PATH'." }
    }
    Write-Host "   Instalando as bibliotecas (pode levar alguns minutos na primeira vez)..."
    Rodar $pasta @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt") "instalacao das bibliotecas"
    Ok "Bibliotecas em dia."
}

function AtualizarBanco($pasta) {
    Rodar $pasta @("manage.py", "migrate", "--noinput") "migrate"
    Rodar $pasta @("manage.py", "inicializar") "inicializar"
    Rodar $pasta @("manage.py", "preparar_rg2026", "--sem-backup") "preparar_rg2026"
    Rodar $pasta @("manage.py", "collectstatic", "--noinput", "-v", "0") "collectstatic"
    Ok "Banco e arquivos estaticos atualizados."
}

function DadosDe($pasta) {
    $d = LerEnv $pasta "SIRG_DADOS_DIR" ""
    if ($d) { return $d }
    return (Join-Path $pasta "dados")
}

function CopiarDadosDaProducao() {
    $origemDados = DadosDe $PRD
    $banco = Join-Path $origemDados "sirg.sqlite3"
    if (-not (Test-Path $banco)) { Aviso "Nao achei o banco da producao em $banco. A homologacao comeca vazia."; return }
    $destDados = Join-Path $HML "dados"
    New-Item -ItemType Directory -Force -Path $destDados | Out-Null
    $tmp = Join-Path $destDados "sirg.sqlite3.novo"
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    # copia consistente do SQLite (funciona com a producao no ar)
    $codigo = "import sqlite3,sys; a=sqlite3.connect(sys.argv[1]); b=sqlite3.connect(sys.argv[2]); a.backup(b); b.close(); a.close()"
    & (Python $HML) -c $codigo $banco $tmp
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $tmp)) { Falhar "nao foi possivel copiar o banco da producao" }
    Move-Item $tmp (Join-Path $destDados "sirg.sqlite3") -Force -ErrorAction Stop
    $arq = Join-Path $origemDados "arquivos"
    if (Test-Path $arq) {
        robocopy $arq (Join-Path $destDados "arquivos") /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
        $global:LASTEXITCODE = 0
    }
    Ok "Dados da producao copiados para a homologacao (banco e arquivos enviados)."
}

function PrepararEnvHml() {
    $envHml = Join-Path $HML ".env"
    if (-not (Test-Path $envHml)) {
        $base = Join-Path $PRD ".env"
        if (-not (Test-Path $base)) { $base = Join-Path $HML ".env.exemplo" }
        Copy-Item $base $envHml -ErrorAction Stop
        Ok ".env da homologacao criado a partir de $base"
    }
    if ((LerEnv $HML "SIRG_DB" "sqlite").ToLower() -eq "postgres") {
        Falhar "o .env usa PostgreSQL: a homologacao apontaria para o banco da producao. Ajuste SIRG_DB_NOME no $envHml antes."
    }
    $hosts = (LerEnv $HML "SIRG_ALLOWED_HOSTS" "localhost,127.0.0.1").Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    if ($hosts -notcontains $HML_HOST) { $hosts = @($hosts) + $HML_HOST }
    foreach ($h in @("hml-sirg.softwares.net.br", "sirg-hml.softwares.net.br", "hml.sirg.softwares.net.br")) { if ($hosts -notcontains $h) { $hosts = @($hosts) + $h } }
    foreach ($h in @("localhost", "127.0.0.1")) { if ($hosts -notcontains $h) { $hosts = @($hosts) + $h } }
    $origens = (LerEnv $HML "SIRG_CSRF_TRUSTED_ORIGINS" "").Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -and ($_ -notmatch ':800[12]$') }
    foreach ($o in @("https://$HML_HOST", "https://sirg-hml.softwares.net.br", "https://hml.sirg.softwares.net.br", "http://127.0.0.1:$HML_PORTA", "http://localhost:$HML_PORTA")) { if ($origens -notcontains $o) { $origens = @($origens) + $o } }
    GravarEnv $envHml "SIRG_AMBIENTE" "hml"
    GravarEnv $envHml "SIRG_PORTA" "$HML_PORTA"
    GravarEnv $envHml "SIRG_TAREFA" $HML_TAREFA
    GravarEnv $envHml "SIRG_ALLOWED_HOSTS" ($hosts -join ",")
    GravarEnv $envHml "SIRG_CSRF_TRUSTED_ORIGINS" ($origens -join ",")
    GravarEnv $envHml "SIRG_URL_BASE" "https://$HML_HOST"
    # nunca dividir pasta de dados ou de backup com a producao (o rodizio de backups apagaria os da producao)
    GravarEnv $envHml "SIRG_DADOS_DIR" (Join-Path $HML "dados")
    GravarEnv $envHml "SIRG_BACKUP_DIR" (Join-Path $HML "dados\backups")
    Ok ".env da homologacao: porta $HML_PORTA, endereco https://$HML_HOST"
}

function GuardarVersaoAnterior() {
    $v = Versao $PRD
    if (-not $v) { return }
    $dest = Join-Path $Raiz ("versoes_anteriores\v" + $v + "_" + (Get-Date -Format "yyyyMMdd_HHmm"))
    robocopy $PRD $dest /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD dados .venv staticfiles __pycache__ /XF .env *.pyc | Out-Null
    $global:LASTEXITCODE = 0
    $todas = @(Get-ChildItem (Join-Path $Raiz "versoes_anteriores") -Directory | Sort-Object Name)
    if ($todas.Count -gt 3) { $todas[0..($todas.Count - 4)] | ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue } }
    Ok "Codigo da versao $v guardado em $dest"
}

# ------------------------------------------------------------------------------------------------------------
$nova = Versao $Origem
if (-not $nova) { Falhar "a pasta $Origem nao parece ser do SiRG (falta config\settings.py)." }

if ($Alvo -eq "hml") {
    Titulo "Homologacao: versao $nova em $HML"
    $primeira = -not (Test-Path (Join-Path $HML "manage.py"))
    if (-not $primeira) {
        Titulo "1) Parando a homologacao"
        PararServidor $HML $HML_TAREFA (Porta $HML $HML_PORTA)
        if ((Porta $HML $HML_PORTA) -ne $HML_PORTA) { PararServidor $HML $HML_TAREFA $HML_PORTA }
    }
    $outro = PortaDeOutroPrograma $HML_PORTA
    if ($outro) { Falhar "a porta $HML_PORTA esta ocupada por outro programa: $outro. Libere a porta ou troque HML_PORTA no implantar.ps1." }
    Titulo "2) Copiando os arquivos"
    CopiarCodigo $HML
    PrepararEnvHml
    Titulo "3) Ambiente Python"
    GarantirVenv $HML
    Titulo "4) Dados"
    $temBanco = Test-Path (Join-Path $HML "dados\sirg.sqlite3")
    if (-not $temBanco) {
        CopiarDadosDaProducao
    } else {
        if ($Automatico) { $r = $(if ($CopiarDados) { "S" } else { "N" }) }
        else { $r = Read-Host "   Trocar os dados da homologacao por uma copia atual da producao? Os testes feitos na homologacao se perdem. (S/N, Enter = N)" }
        if ($r -match '^[sS]') { CopiarDadosDaProducao } else { Ok "Dados da homologacao mantidos." }
    }
    Titulo "5) Atualizando o banco"
    AtualizarBanco $HML
    Titulo "6) Ligando a homologacao"
    netsh advfirewall firewall delete rule name="SiRG HML porta 8002" 2>$null | Out-Null
    netsh advfirewall firewall delete rule name="SiRG HML porta $HML_PORTA" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="SiRG HML porta $HML_PORTA" dir=in action=allow protocol=TCP localport=$HML_PORTA 2>$null | Out-Null
    LigarServidor $HML $HML_TAREFA (Porta $HML $HML_PORTA) | Out-Null
    Write-Host ""
    Write-Host "Homologacao pronta: versao $nova" -ForegroundColor Green
    Write-Host "   Neste computador: http://127.0.0.1:$HML_PORTA"
    Write-Host "   Pela internet:    https://$HML_HOST  (aponte o tunel da Cloudflare para http://127.0.0.1:$HML_PORTA)"
    Write-Host "   Depois de testar, rode o subir_prd.bat para levar esta versao para a producao."
} else {
    $tarefa = LerEnv $PRD "SIRG_TAREFA" "SiRG - Servidor"
    $porta = Porta $PRD 8001
    if (-not (Test-Path (Join-Path $PRD "manage.py"))) { Falhar "nao achei a producao em $PRD." }
    $atual = Versao $PRD
    $emHml = Versao $HML
    Titulo "Producao: versao $atual -> $nova em $PRD"
    if ($emHml -ne $nova) {
        Aviso "A homologacao esta com a versao '$emHml', nao com a $nova deste zip."
        # automatico: o implantador ja conferiu que este codigo foi instalado na homologacao antes
        if ($Automatico) { $r = "S" } else { $r = Read-Host "   Subir a $nova para a producao mesmo sem ter testado na homologacao? (S/N, Enter = N)" }
        if ($r -notmatch '^[sS]') { Write-Host "Nada foi alterado."; return }
    }
    Titulo "1) Backup dos dados da producao"
    Rodar $PRD @("manage.py", "backup") "backup"
    GuardarVersaoAnterior
    Titulo "2) Parando a producao"
    PararServidor $PRD $tarefa $porta
    $okFinal = $false
    try {
        Titulo "3) Copiando os arquivos"
        CopiarCodigo $PRD
        Titulo "4) Ambiente Python"
        GarantirVenv $PRD
        Titulo "5) Atualizando o banco"
        AtualizarBanco $PRD
        $okFinal = $true
    } finally {
        Titulo "6) Ligando a producao"
        LigarServidor $PRD $tarefa $porta | Out-Null
    }
    if ($okFinal) {
        Write-Host ""
        Write-Host "Producao atualizada para a versao $nova." -ForegroundColor Green
        Write-Host "   Abra o site e aperte Ctrl+F5 para carregar a versao nova."
    }
}
