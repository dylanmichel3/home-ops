# Disk usage breakdown for Home Ops. For each fixed drive, lists the
# largest top-level folders. Prints JSON. Can take several minutes on a
# full drive; app.py runs it in a background thread and caches the result.
$drives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -ne $null }
$result = @()
foreach ($d in $drives) {
    $root = $d.Root
    $entries = @()
    try {
        $items = Get-ChildItem -Path $root -Force -ErrorAction SilentlyContinue
        foreach ($item in $items) {
            $size = 0
            try {
                if ($item.PSIsContainer) {
                    $size = (Get-ChildItem -Path $item.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
                } else {
                    $size = $item.Length
                }
            } catch {}
            if ($null -eq $size) { $size = 0 }
            $entries += [PSCustomObject]@{name = $item.Name; path = $item.FullName; bytes = [long]$size}
        }
    } catch {}
    $entries = @($entries | Sort-Object bytes -Descending | Select-Object -First 15)
    $result += [PSCustomObject]@{
        drive       = $root
        total_bytes = [long]($d.Used + $d.Free)
        free_bytes  = [long]$d.Free
        top         = $entries
    }
}
[PSCustomObject]@{drives = @($result)} | ConvertTo-Json -Compress -Depth 5
