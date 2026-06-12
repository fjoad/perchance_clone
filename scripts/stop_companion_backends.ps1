param(
    [switch]$IncludeJupyter
)

$ErrorActionPreference = "Continue"

function Print-Resources($Label) {
    try {
        $gpu = (& nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits).Trim()
    }
    catch {
        $gpu = "nvidia-smi unavailable"
    }
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
        $totalGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        Write-Host ("[resources] {0}: gpu={1} MiB used/free, ram_free={2}/{3} GiB" -f $Label, $gpu, $freeGb, $totalGb)
    }
    catch {
        Write-Host ("[resources] {0}: gpu={1}" -f $Label, $gpu)
    }
}

function Stop-MatchingProcesses {
    $targets = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "ollama.exe") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -match "stable-diffusion-webui|launch.py|bench_.*a1111|run_gold_production_a1111") -or
        ($_.Name -eq "cmd.exe" -and $_.CommandLine -match "webui-user.bat")
    }

    if ($IncludeJupyter) {
        $targets += Get-CimInstance Win32_Process | Where-Object {
            ($_.Name -eq "python.exe") -and $_.CommandLine -match "jupyter|ipykernel"
        }
    }

    $targets = $targets | Sort-Object ProcessId -Unique
    if (-not $targets) {
        Write-Host "[cleanup] no companion backend processes found"
        return
    }

    foreach ($p in $targets) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Host ("[cleanup] stopped {0} {1}" -f $p.Name, $p.ProcessId)
        }
        catch {
            Write-Host ("[cleanup] skip {0}: {1}" -f $p.ProcessId, $_.Exception.Message)
        }
    }
}

Print-Resources "before cleanup"
Stop-MatchingProcesses
Start-Sleep -Seconds 3
Print-Resources "after cleanup"
