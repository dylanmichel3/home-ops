# Event log digest for Home Ops. Summarizes Critical/Error/Warning events
# from the System and Application logs over the last 24 hours. Prints JSON.
$since = (Get-Date).AddHours(-24)
$raw = @()
foreach ($log in @("System", "Application")) {
    try {
        $raw += Get-WinEvent -FilterHashtable @{LogName = $log; Level = @(1, 2, 3); StartTime = $since} -ErrorAction SilentlyContinue
    } catch {}
}
$groups = $raw | Group-Object -Property LogName, Id, ProviderName | ForEach-Object {
    $g = $_.Group | Sort-Object TimeCreated -Descending
    $first = $g[0]
    $msg = ""
    try { $msg = ($first.Message -replace '\s+', ' ').Trim() } catch {}
    if ($msg.Length -gt 220) { $msg = $msg.Substring(0, 220) }
    [PSCustomObject]@{
        log      = $first.LogName
        level    = $first.LevelDisplayName
        event_id = $first.Id
        source   = $first.ProviderName
        count    = $_.Count
        latest   = $first.TimeCreated.ToString("yyyy-MM-dd HH:mm")
        sample   = $msg
    }
}
$rank = @{ Critical = 0; Error = 1; Warning = 2 }
$sorted = @($groups | Sort-Object @{Expression = { $rank[$_.level] }; Ascending = $true}, @{Expression = "count"; Descending = $true} | Select-Object -First 25)
$errCount = @($raw | Where-Object { $_.Level -le 2 }).Count
$warnCount = @($raw | Where-Object { $_.Level -eq 3 }).Count
[PSCustomObject]@{
    window_hours = 24
    total        = $raw.Count
    errors       = $errCount
    warnings     = $warnCount
    groups       = $sorted
} | ConvertTo-Json -Compress -Depth 4
