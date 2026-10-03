# Patch compliance check for Home Ops. Prints JSON to stdout.
# Run from app.py; not meant to be run by hand (but you can: powershell -File patch_check.ps1).
$out = @{}
try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $result = $searcher.Search("IsInstalled=0 and IsHidden=0")
    $titles = @($result.Updates | ForEach-Object { $_.Title } | Select-Object -First 25)
    $out["pending_count"] = $result.Updates.Count
    $out["pending_titles"] = $titles
} catch {
    $out["pending_count"] = -1
    $out["pending_error"] = $_.Exception.Message
}
$reboot = $false
foreach ($p in @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
)) {
    if (Test-Path $p) { $reboot = $true }
}
$out["reboot_required"] = $reboot
try {
    $hf = Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 1
    $out["last_hotfix"] = $hf.InstalledOn.ToString("yyyy-MM-dd")
    $out["last_hotfix_id"] = $hf.HotFixID
} catch {
    $out["last_hotfix"] = $null
}
$out | ConvertTo-Json -Compress -Depth 4
