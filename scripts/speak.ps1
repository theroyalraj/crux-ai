# Single client path to Crux speech on Windows — same contract as speak.sh (no local say).
# Uses curl.exe (ships with Windows 10+). No bash, no jq.
#
# Usage (from repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/speak.ps1 "Plain English text" [0|1] [persona]
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/speak.ps1 --sync "text" [0|1] [persona]
#
# Chain with cd using a semicolon — Windows PowerShell 5.x does not support && :
#   cd d:\code\crux-ai; powershell -NoProfile -ExecutionPolicy Bypass -File scripts\speak.ps1 "Hello" 1
#
# Env: CRUX_BASE_URL (default http://127.0.0.1:9090)

$ErrorActionPreference = 'Stop'

$sync = $false
$rest = [System.Collections.ArrayList]@($args)
if ($rest.Count -gt 0 -and $rest[0] -eq '--sync') {
    $sync = $true
    $rest.RemoveAt(0)
}
if ($rest.Count -lt 1) {
    Write-Error 'usage: speak.ps1 [--sync] "text" [priority 0|1] [persona]'
}

$text = [string]$rest[0]
$priority = if ($rest.Count -gt 1) { [string]$rest[1] } else { '0' }
$persona = if ($rest.Count -gt 2) { [string]$rest[2] } else { '' }

$base = if ($env:CRUX_BASE_URL -and $env:CRUX_BASE_URL.Trim()) {
    $env:CRUX_BASE_URL.Trim().TrimEnd('/')
} else {
    'http://127.0.0.1:9090'
}
$pbool = ($priority -eq '1')

$body = [ordered]@{ text = $text; priority = $pbool }
if ($persona) {
    $body['persona'] = $persona
}
$json = $body | ConvertTo-Json -Compress

$uri = if ($sync) { "$base/speak" } else { "$base/speak-async" }

# Pipe JSON to curl so special characters stay safe (same idea as speak.sh -d @-)
if ($sync) {
    $json | & curl.exe -sS -m 300 -X POST $uri -H 'Content-Type: application/json' -d '@-'
} else {
    $json | & curl.exe -sS -X POST $uri -H 'Content-Type: application/json' -d '@-'
}
Write-Output ''
