# Para ou liga o servidor do SiRG (usado pelo atualizar.bat). Uso: servico.ps1 parar | ligar
# Para: encerra a tarefa agendada e todos os processos do servidor DESTA pasta (pelo arquivo dados\servidor.pid,
# pela janela do servidor.bat, pelo Python da .venv desta pasta e pelo programa que ocupa a porta do SiRG).
# Nao mexe em outros sistemas (ex.: SiMED), que ficam em outras pastas e portas.
param([string]$acao = "parar")
$ErrorActionPreference = "SilentlyContinue"
$pasta = $PSScriptRoot.TrimEnd("\")
$tarefa = "SiRG - Servidor"
$envArq = Join-Path $pasta ".env"
if (Test-Path $envArq) { foreach ($l in Get-Content $envArq) { if ($l -match '^\s*SIRG_TAREFA\s*=\s*(.+)$') { $tarefa = $Matches[1].Trim() } } }

function Porta {
    $p = 8001
    $env_ = Join-Path $pasta ".env"
    if (Test-Path $env_) {
        foreach ($l in Get-Content $env_) { if ($l -match '^\s*SIRG_PORTA\s*=\s*(\d+)') { $p = [int]$Matches[1] } }
    }
    return $p
}

function Contem($texto, $parte) {
    return ($texto -and $texto.IndexOf($parte, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}

function Parar {
    schtasks /End /TN $tarefa 2>$null | Out-Null
    $todos = @(Get-CimInstance Win32_Process)
    $alvos = New-Object System.Collections.Generic.HashSet[int]
    # 1. o PID que o proprio servidor gravou ao iniciar
    $pidArq = Join-Path $pasta "dados\servidor.pid"
    if (Test-Path $pidArq) {
        $n = 0
        if ([int]::TryParse((Get-Content $pidArq -Raw).Trim(), [ref]$n)) {
            $p = Get-Process -Id $n -ErrorAction SilentlyContinue
            if ($p -and $p.ProcessName -like "python*") { [void]$alvos.Add($n) }   # arquivo velho: o numero pode ser de outro programa
        }
    }
    # 2. a janela do servidor.bat desta pasta e 3. o Python da .venv desta pasta (com os processos filhos)
    $venv = Join-Path $pasta ".venv\"
    $raizes = $todos | Where-Object {
        ($_.Name -eq "cmd.exe" -and (Contem $_.CommandLine (Join-Path $pasta "servidor.bat"))) -or
        ((Contem $_.ExecutablePath $venv) -and (Contem $_.CommandLine "servir.py"))
    }
    foreach ($r in $raizes) { [void]$alvos.Add([int]$r.ProcessId) }
    # 4. quem esta ouvindo na porta do SiRG, se for Python
    $porta = Porta
    foreach ($c in @(Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($p.ProcessName -like "python*") { [void]$alvos.Add([int]$c.OwningProcess) }
    }
    # filhos de cada alvo (o python.exe da .venv abre outro Python por baixo)
    $fila = New-Object System.Collections.Generic.Queue[int]
    foreach ($a in $alvos) { $fila.Enqueue($a) }
    while ($fila.Count -gt 0) {
        $pai = $fila.Dequeue()
        foreach ($f in $todos | Where-Object { $_.ParentProcessId -eq $pai }) {
            if ($alvos.Add([int]$f.ProcessId)) { $fila.Enqueue([int]$f.ProcessId) }
        }
    }
    $alvos.Remove($PID) | Out-Null
    $n = 0
    foreach ($a in $alvos) { if (Get-Process -Id $a -ErrorAction SilentlyContinue) { Stop-Process -Id $a -Force -ErrorAction SilentlyContinue; $n++ } }
    Remove-Item $pidArq -Force -ErrorAction SilentlyContinue
    # espera a porta ficar livre
    for ($i = 0; $i -lt 20; $i++) {
        if (-not (Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($n -gt 0) { Write-Host "   Servidor parado ($n processo(s) encerrado(s))." } else { Write-Host "   O servidor ja estava parado." }
}

function Ligar {
    $porta = Porta
    schtasks /Run /TN $tarefa 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   A tarefa agendada '$tarefa' nao existe neste computador. Abra o servidor.bat para ligar o SiRG."
        return
    }
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue) { Write-Host "   Servidor ligado na porta $porta."; return }
    }
    Write-Host "   A tarefa foi iniciada, mas o servidor ainda nao respondeu na porta $porta. Aguarde um minuto e abra o site."
}

if ($acao -eq "ligar") { Ligar } else { Parar }
