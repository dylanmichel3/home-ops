# install-autostart.ps1
#
# Registers a Windows Task Scheduler task that starts Home Ops (app.py)
# automatically at logon, using pythonw.exe so no console window stays open.
# The task waits 1 minute after logon (so Tailscale has time to bring up the
# PC's tailnet address, which the app binds to), restarts on failure up to
# 3 times, and has no execution time limit.
#
# Run once from the home-ops folder:
#   powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
#
# Safe to re-run: it replaces any existing "Home Ops" task.
# No admin rights needed; the task runs as your user at logon.

$ErrorActionPreference = "Stop"

$TaskName = "Home Ops"
$AppDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppPath  = Join-Path $AppDir "app.py"

if (-not (Test-Path $AppPath)) {
    throw "app.py not found next to this script ($AppPath). Run this script from the home-ops folder."
}
if (-not (Test-Path (Join-Path $AppDir "config.json"))) {
    Write-Warning "config.json not found in $AppDir - create it from config.example.json first, or the app will refuse to start."
}

# --- Find a real pythonw.exe -------------------------------------------------
# Avoid the Microsoft Store stubs under WindowsApps: they are app-execution
# aliases, not real installs, and they fail under Task Scheduler.
function Find-Pythonw {
    # 1. Python launcher ("py -0p" lists real installs with their paths)
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher -and $pyLauncher.Source -notlike "*WindowsApps*") {
        foreach ($line in (& $pyLauncher.Source -0p 2>$null)) {
            if ($line -match "(\S:\\.*python\.exe)\s*$") {
                $candidate = Join-Path (Split-Path -Parent $Matches[1]) "pythonw.exe"
                if (Test-Path $candidate) { return $candidate }
            }
        }
    }
    # 2. pythonw.exe on PATH, as long as it is not the Store stub
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { return $cmd.Source }
    # 3. Standard per-user install location
    $base = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $base) {
        $hit = Get-ChildItem -Path $base -Filter "pythonw.exe" -Recurse -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

$pythonw = Find-Pythonw
if (-not $pythonw) {
    throw "No real pythonw.exe found (only the Microsoft Store stub, or none). Install Python 3.11+ from python.org, tick 'Add python.exe to PATH', install requirements.txt with that Python, then re-run this script."
}
Write-Host "Using Python: $pythonw"

# --- Register the task -------------------------------------------------------
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$AppPath`"" -WorkingDirectory $AppDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"   # let Tailscale connect before the app tries to bind its address

$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Start Home Ops (app.py) at logon" -Force | Out-Null
Write-Host "Task '$TaskName' registered: runs at logon (1 minute delay), restarts on failure."

# --- Start it now and verify -------------------------------------------------
Write-Host "Starting Home Ops now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

$hostAddr = "127.0.0.1"
$port = 5000
$cfgPath = Join-Path $AppDir "config.json"
if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
        if ($cfg.host) { $hostAddr = $cfg.host }
        if ($cfg.port) { $port = $cfg.port }
    } catch { Write-Warning "Could not parse config.json; verifying on 127.0.0.1:5000 instead." }
}

try {
    Invoke-RestMethod -Uri "http://${hostAddr}:$port/api/health" -TimeoutSec 10 | Out-Null
    Write-Host "Verified: Home Ops is up and answering on http://${hostAddr}:$port/api/health"
} catch {
    Write-Warning "Task is registered and started, but /api/health did not answer: $($_.Exception.Message)"
    Write-Warning "Run 'python app.py' from $AppDir once to see the startup error in plain text."
}
