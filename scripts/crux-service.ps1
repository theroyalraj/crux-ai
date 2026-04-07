# Crux process control for Windows (PowerShell).
# Mirrors scripts/crux-service.sh where it makes sense (no bash, lsof, or Terminal.app).
#
# Usage (from repo root):
#   pwsh scripts/crux-service.ps1 stop-server
#   pwsh scripts/crux-service.ps1 start-server
#   pwsh scripts/crux-service.ps1 start-server-fg        # foreground in this window (best for TTS)
#   pwsh scripts/crux-service.ps1 start-server-terminal  # new PowerShell window, foreground
#   pwsh scripts/crux-service.ps1 restart-server
#   pwsh scripts/crux-service.ps1 restart-all
#   pwsh scripts/crux-service.ps1 docker-restart
#   pwsh scripts/crux-service.ps1 status
#
# Env: CRUX_PORT (default 9090), COMPOSE_FILE (default repo/docker/docker-compose.yml)
#Requires -Version 5.1

param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "stop-server",
        "stop-all",
        "start-server",
        "start-server-fg",
        "start-server-terminal",
        "start-all",
        "restart-server",
        "restart-all",
        "restart-server-terminal",
        "restart-all-terminal",
        "docker-up",
        "docker-down",
        "docker-restart",
        "status",
        "help"
    )]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CruxPort = if ($env:CRUX_PORT) { [int]$env:CRUX_PORT } else { 9090 }
$ComposeFile = if ($env:COMPOSE_FILE) { $env:COMPOSE_FILE } else { Join-Path $Root "docker\docker-compose.yml" }
$LogDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "crux-server.log"
$PidFile = Join-Path $LogDir "crux-server.pid"
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"

function Usage {
    Write-Host "Crux service control (Windows). Run from repo root."
    Write-Host ""
    Write-Host "  stop-server              Stop listener on CRUX_PORT (default 9090)"
    Write-Host "  stop-all                 stop-server + docker compose down"
    Write-Host "  start-server             API in background -> logs/crux-server.log"
    Write-Host "  start-server-fg          Foreground this window (best for ffplay TTS)"
    Write-Host "  start-server-terminal    New PowerShell window, foreground server"
    Write-Host "  start-all                docker compose up -d + start-server"
    Write-Host "  restart-server           stop-server + start-server"
    Write-Host "  restart-all              docker restart + stop-server + start-server"
    Write-Host "  restart-server-terminal  stop-server + start-server-terminal"
    Write-Host "  restart-all-terminal     docker restart + restart-server-terminal"
    Write-Host "  docker-up | docker-down | docker-restart"
    Write-Host "  status                   health, listeners, docker ps"
    Write-Host ""
    Write-Host "Wrapper: pwsh scripts/restart.ps1 all | server"
    exit 1
}

function Require-Venv {
    if (-not (Test-Path $PythonExe)) {
        Write-Error "Missing .venv - create it and install deps (see CONTRIBUTING.md / make setup on macOS)."
    }
}

function Stop-ListenerOnPort {
    param([int]$Port)
    $killed = $false

    $pids = @()
    try {
        $pids = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {}

    if ($pids.Count -eq 0) {
        foreach ($line in (netstat -ano 2>$null)) {
            if ($line -match "LISTENING" -and $line -match ":$Port\s") {
                $cols = ($line -split "\s+") | Where-Object { $_ -ne "" }
                $last = $cols[-1]
                if ($last -match "^\d+$") { $pids += [int]$last }
            }
        }
        $pids = $pids | Select-Object -Unique
    }

    foreach ($procId in $pids) {
        if (-not $procId -or $procId -eq 0) { continue }
        try {
            $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($p) {
                Write-Host "Stopping PID $procId ($($p.ProcessName)) on port $Port"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $killed = $true
            }
        } catch {}
    }

    if (-not $killed) {
        Write-Host "No process listening on port $Port"
    }

    Start-Sleep -Milliseconds 600

    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {}

    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

function Wait-Health {
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$CruxPort/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) {
                Write-Host "ok: http://127.0.0.1:$CruxPort/health"
                return
            }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    Write-Warning "Health check timed out - see $LogFile"
}

function Start-CruxServerBackground {
    Require-Venv
    try {
        $existing = Get-NetTCPConnection -LocalPort $CruxPort -State Listen -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Error "Port $CruxPort is already in use - run: pwsh scripts/crux-service.ps1 stop-server"
        }
    } catch {}

    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

    Write-Host "Starting Crux in background - log: $LogFile"
    $inner = "cd /d `"$Root`" && `"$PythonExe`" -m server.main >> `"$LogFile`" 2>&1"
    $p = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $inner) -WindowStyle Hidden -PassThru
    $p.Id | Set-Content -Path $PidFile -Encoding ascii
    Write-Host "Started cmd hosting Python, PID $($p.Id)"
    Wait-Health
}

function Start-CruxServerForeground {
    Require-Venv
    Set-Location $Root
    & $PythonExe -m server.main
}

function Start-CruxServerNewTerminal {
    Require-Venv
    $cmd = "& `"$PythonExe`" -m server.main"
    $started = $false
    foreach ($shell in @("pwsh.exe", "powershell.exe")) {
        try {
            Start-Process -FilePath $shell -WorkingDirectory $Root -ArgumentList @(
                "-NoExit",
                "-Command",
                $cmd
            ) -ErrorAction Stop
            $started = $true
            break
        } catch {}
    }
    if (-not $started) {
        Write-Error "Could not start pwsh or powershell - run: pwsh scripts/crux-service.ps1 start-server-fg"
    }
    Write-Host "Opened new window - server runs there (close window to stop)."
}

function Invoke-DockerUp {
    if (-not (Test-Path $ComposeFile)) { Write-Error "Missing: $ComposeFile" }
    docker compose -f $ComposeFile up -d
}

function Invoke-DockerDown {
    if (-not (Test-Path $ComposeFile)) { Write-Error "Missing: $ComposeFile" }
    docker compose -f $ComposeFile down
}

function Invoke-DockerRestart {
    if (-not (Test-Path $ComposeFile)) { Write-Error "Missing: $ComposeFile" }
    docker compose -f $ComposeFile restart
}

function Show-Status {
    Write-Host "CRUX_PORT=$CruxPort"
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$CruxPort/health" -UseBasicParsing -TimeoutSec 2
        Write-Host $r.Content
    } catch {
        Write-Host "health: (no response)"
    }
    Write-Host "--- listen ($CruxPort) ---"
    try {
        Get-NetTCPConnection -LocalPort $CruxPort -State Listen -ErrorAction SilentlyContinue |
        Format-Table -AutoSize
    } catch {
        netstat -ano | Select-String ":$CruxPort "
    }
    Write-Host "--- docker ---"
    if (Test-Path $ComposeFile) {
        docker compose -f $ComposeFile ps 2>$null
    } else {
        Write-Host "no compose file"
    }
    if (Test-Path $PidFile) {
        Write-Host "--- pid file --- $(Get-Content $PidFile -Raw)"
    }
}

switch ($Command) {
    "help" { Usage }
    "stop-server" { Stop-ListenerOnPort $CruxPort }
    "stop-all" {
        Stop-ListenerOnPort $CruxPort
        Invoke-DockerDown
    }
    "start-server-fg" { Start-CruxServerForeground }
    "start-server-terminal" { Start-CruxServerNewTerminal }
    "start-server" { Start-CruxServerBackground }
    "start-all" {
        Invoke-DockerUp
        Start-CruxServerBackground
    }
    "restart-server" {
        Stop-ListenerOnPort $CruxPort
        Start-CruxServerBackground
    }
    "restart-all" {
        Invoke-DockerRestart
        Stop-ListenerOnPort $CruxPort
        Start-CruxServerBackground
    }
    "restart-server-terminal" {
        Stop-ListenerOnPort $CruxPort
        Start-CruxServerNewTerminal
    }
    "restart-all-terminal" {
        Invoke-DockerRestart
        Stop-ListenerOnPort $CruxPort
        Start-CruxServerNewTerminal
    }
    "docker-up" { Invoke-DockerUp }
    "docker-down" { Invoke-DockerDown }
    "docker-restart" { Invoke-DockerRestart }
    "status" { Show-Status }
}
