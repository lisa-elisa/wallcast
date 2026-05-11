# Hand Sparks launcher — one window, close it to stop everything.
# Usage:
#   .\start.ps1              (default: no rotation)
#   .\start.ps1 -Rotate 180  (rotate phone camera frame)
param(
    [ValidateSet(0,90,180,270)]
    [int]$Rotate = 0
)

$proj     = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $proj
$servePy  = Join-Path $repoRoot "shared\serve.py"
$adb      = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"

Set-Location $proj

# ── Kill any leftover processes on our ports ──────────────────────────────────
Write-Host "Stopping old instances..."
Get-NetTCPConnection -LocalPort 8765,8766,8000 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

# ── Start shared HTTP server hidden in background ─────────────────────────────
$pServe = Start-Process python `
    -ArgumentList @($servePy, "--open", "/hand_sparks/index.html") `
    -PassThru -WindowStyle Hidden
Write-Host "HTTP server started (PID $($pServe.Id))"

# ── ADB port forwarding ───────────────────────────────────────────────────────
if (Test-Path $adb) {
    Start-Sleep -Seconds 1
    $r1 = & $adb reverse tcp:8000 tcp:8000 2>&1
    $r2 = & $adb reverse tcp:8766 tcp:8766 2>&1
    if ($r1 -match "error" -or $r2 -match "error") {
        Write-Host "[ADB] WARNING: forwarding failed — phone may not be connected" -ForegroundColor Yellow
    } else {
        Write-Host "[ADB] Ports forwarded: 8000 and 8766" -ForegroundColor Green
    }
} else {
    Write-Host "[ADB] adb.exe not found — USB forwarding skipped" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  Browser : http://localhost:8000/hand_sparks/index.html"
Write-Host "  Phone   : http://localhost:8000/shared/phone_camera.html  (USB/ADB)"
if ($Rotate -ne 0) { Write-Host "  Rotate  : $Rotate deg" }
Write-Host ""
Write-Host "Close this window or press Ctrl+C to stop everything."
Write-Host "─────────────────────────────────────────────────────────"

# ── Cleanup: kill serve.py when this window closes ───────────────────────────
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Stop-Process -Id $pServe.Id -Force -ErrorAction SilentlyContinue
} | Out-Null

# ── Run server.py in foreground (its logs appear here) ───────────────────────
$serverArgs = @("server.py", "--phone", "--debug")
if ($Rotate -ne 0) { $serverArgs += "--rotate"; $serverArgs += "$Rotate" }

try {
    & python @serverArgs
} finally {
    Write-Host "`nStopping HTTP server..."
    Stop-Process -Id $pServe.Id -Force -ErrorAction SilentlyContinue
    Write-Host "All stopped."
}
