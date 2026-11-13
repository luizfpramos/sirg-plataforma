# Implantador automatico do SiRG (roda no PC da producao, pela tarefa agendada "SiRG - Implantador").
#
# A cada execucao (de 5 em 5 minutos):
#   1. busca no GitHub os ramos implantar/hml e implantar/prd (o GitHub Actions so atualiza esses ramos
#      depois que os testes passam);
#   2. se implantar/hml mudou: instala aquele codigo na homologacao (implantar.ps1 -Alvo hml);
#   3. se implantar/prd mudou: instala na producao (implantar.ps1 -Alvo prd), SO se esse codigo ja foi
#      instalado na homologacao antes;
#   4. grava o resultado em <ambiente>\dados\implantacao.json (aparece na tela Sobre do SiRG) e no log.
#
# Nada e enviado ao GitHub: a chave usada so tem permissao de leitura.
# Este arquivo e so ASCII de proposito (o PowerShell 5 le scripts sem BOM como ANSI).
param([switch]$Agora)
$ErrorActionPreference = "Continue"
$Base = $PSScriptRoot
$Repo = Join-Path $Base "repo"
$ArqEstado = Join-Path $Base "estado.json"
$ArqConfig = Join-Path $Base "config.json"
$PastaLog = Join-Path $Base "logs"
New-Item -ItemType Directory -Force -Path $PastaLog | Out-Null
$Log = Join-Path $PastaLog ("implantador-" + (Get-Date -Format "yyyy-MM") + ".log")

function Logar($t) { $l = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "  " + $t; Add-Content -Path $Log -Value $l -Encoding UTF8; Write-Host $l }

# so uma execucao por vez
$trava = New-Object System.Threading.Mutex($false, "Global\SiRG-Implantador")
if (-not $trava.WaitOne(0)) { exit 0 }
try {
    $cfg = Get-Content $ArqConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    $Raiz = $cfg.raiz
    $chave = ($Base -replace '\\', '/') + "/chave_github"
    $kh = ($Base -replace '\\', '/') + "/known_hosts"
    $env:GIT_SSH_COMMAND = "ssh -i `"$chave`" -o IdentitiesOnly=yes -o UserKnownHostsFile=`"$kh`" -o StrictHostKeyChecking=accept-new"
    $env:GIT_TERMINAL_PROMPT = "0"
    function G { & git -c safe.directory=* -C $Repo @args }

    if (-not (Test-Path (Join-Path $Repo ".git"))) {
        Logar "Clonando $($cfg.repositorio)"
        & git -c safe.directory=* clone --no-checkout --quiet $cfg.repositorio $Repo 2>&1 | ForEach-Object { Logar "   $_" }
        if ($LASTEXITCODE -ne 0) { Logar "ERRO: nao foi possivel clonar o repositorio."; exit 1 }
    }
    $saida = G fetch --prune --quiet origin "+refs/heads/implantar/*:refs/remotes/origin/implantar/*" 2>&1
    if ($LASTEXITCODE -ne 0) { Logar "ERRO ao buscar no GitHub: $saida"; exit 1 }

    $estado = @{ hml = ""; prd = ""; hml_falhou = ""; prd_falhou = "" }
    if (Test-Path $ArqEstado) {
        $e = Get-Content $ArqEstado -Raw | ConvertFrom-Json
        foreach ($k in @("hml", "prd", "hml_falhou", "prd_falhou")) { if ($e.$k) { $estado[$k] = [string]$e.$k } }
    }
    function SalvarEstado { $estado | ConvertTo-Json | Set-Content -Path $ArqEstado -Encoding UTF8 }

    function Registrar($alvo, $commit, $versao, $ok, $erro) {
        $pasta = if ($alvo -eq "hml") { Join-Path $Raiz "hml\sirg-plataforma" } else { Join-Path $Raiz "producao\sirg-plataforma" }
        $dados = Join-Path $pasta "dados"
        if (-not (Test-Path $dados)) { return }
        $arq = Join-Path $dados "implantacao.json"
        $lista = @()
        if (Test-Path $arq) { try { $lista = @(Get-Content $arq -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { $lista = @() } }
        $lista += [pscustomobject]@{ quando = (Get-Date -Format "dd/MM/yyyy HH:mm"); alvo = $alvo; versao = $versao;
                                     commit = $commit; ok = $ok; erro = $erro }
        if ($lista.Count -gt 30) { $lista = $lista[($lista.Count - 30)..($lista.Count - 1)] }
        ConvertTo-Json -InputObject @($lista) -Depth 3 | Set-Content -Path $arq -Encoding UTF8
    }

    function Instalar($alvo, $commit) {
        $tmp = Join-Path $env:TEMP ("sirg-implantar-" + $commit.Substring(0, 12))
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        $zip = Join-Path $tmp "codigo.zip"
        G archive --format=zip --prefix=sirg-plataforma/ -o $zip $commit 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { return @{ ok = $false; versao = ""; erro = "git archive falhou" } }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $origem = Join-Path $tmp "sirg-plataforma"
        $versao = ""
        foreach ($l in Get-Content (Join-Path $origem "config\settings.py")) { if ($l -match '^\s*SIRG_VERSAO\s*=\s*"([^"]+)"') { $versao = $Matches[1] } }
        $saidaLog = Join-Path $PastaLog ("instalacao-" + $alvo + "-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
        Logar "Instalando $alvo : versao $versao, codigo $($commit.Substring(0, 8)) (detalhes em $saidaLog)"
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $origem "implantacao\implantar.ps1") `
            -Alvo $alvo -Origem $origem -Raiz $Raiz -Automatico *> $saidaLog
        $codigo = $LASTEXITCODE
        $texto = Get-Content $saidaLog -Raw -ErrorAction SilentlyContinue
        $erro = ""
        if ($codigo -ne 0 -or $texto -match "ERRO:") {
            $linhas = @(Get-Content $saidaLog -ErrorAction SilentlyContinue | Where-Object { $_.Trim() })
            $erro = ($linhas | Select-Object -Last 12) -join "`n"
            if (-not $erro) { $erro = "codigo de saida $codigo" }
        }
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
        return @{ ok = (-not $erro); versao = $versao; erro = $erro }
    }

    foreach ($alvo in @("hml", "prd")) {
        $commit = (G rev-parse --verify --quiet "refs/remotes/origin/implantar/$alvo" 2>$null)
        if (-not $commit) { continue }
        $commit = "$commit".Trim()
        if ($commit -eq $estado[$alvo]) { continue }                       # ja instalado
        if ($commit -eq $estado["${alvo}_falhou"] -and -not $Agora) { continue }   # ja falhou: espera codigo novo
        if ($alvo -eq "prd") {
            # a producao so recebe codigo que ja foi instalado na homologacao
            if (-not $estado["hml"]) { Logar "PRD: aguardando a primeira instalacao na homologacao."; continue }
            G merge-base --is-ancestor $commit $estado["hml"] 2>$null
            if ($LASTEXITCODE -ne 0) {
                if ($estado["prd_falhou"] -ne $commit) {
                    $msg = "o codigo $($commit.Substring(0, 8)) ainda nao foi instalado na homologacao; a producao nao foi alterada."
                    Logar "PRD recusada: $msg"; Registrar "prd" $commit "" $false $msg
                    $estado["prd_falhou"] = $commit; SalvarEstado
                }
                continue
            }
        }
        $r = Instalar $alvo $commit
        if ($r.ok) {
            Logar "$alvo : versao $($r.versao) instalada."
            $estado[$alvo] = $commit; $estado["${alvo}_falhou"] = ""
        } else {
            Logar "$alvo : FALHOU. $($r.erro)"
            $estado["${alvo}_falhou"] = $commit
        }
        Registrar $alvo $commit $r.versao $r.ok $r.erro
        SalvarEstado
    }
} catch {
    Logar "ERRO inesperado: $_"
    exit 1
} finally {
    $trava.ReleaseMutex()
}
