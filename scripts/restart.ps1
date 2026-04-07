# Back-compat wrapper for Windows - see scripts/crux-service.ps1 for full CLI.
param(
    [Parameter(Position = 0)]
    [ValidateSet("all", "server")]
    [string]$Target
)

if (-not $Target) {
    Write-Host "usage: pwsh scripts/restart.ps1 all | server" -ForegroundColor Yellow
    Write-Host "  all    - docker compose restart, free CRUX_PORT, start server (background)"
    Write-Host "  server - free CRUX_PORT, start server (background)"
    exit 1
}

$here = $PSScriptRoot
$cmd = if ($Target -eq "all") { "restart-all" } else { "restart-server" }
& (Join-Path $here "crux-service.ps1") $cmd
