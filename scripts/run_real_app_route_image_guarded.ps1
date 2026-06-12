param(
    [double]$MinFreeRamGb = 6.0,
    [double]$MaxCommitRatio = 0.86,
    [int]$MaxVramUsedMiB = 11400,
    [int]$PollSeconds = 2,
    [string]$ResolutionPreset = "",
    [string]$SmokeScriptRel = "scripts\smoke_real_app_route_image.py",
    [string]$SmokeSlug = "codex-echidna-real-route-smoke"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$PythonExe = "F:\anaconda3\envs\companion_v1\python.exe"
$SmokeScript = Join-Path $RepoRoot $SmokeScriptRel
$WatchdogLog = Join-Path $RepoRoot ("runtime\logs\real_app_route_watchdog_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

function Set-FOnlyEnv {
    $env:HF_HOME = "F:\huggingface\models"
    $env:HF_HUB_CACHE = "F:\huggingface\models\hub"
    $env:HUGGINGFACE_HUB_CACHE = "F:\huggingface\models\hub"
    $env:TRANSFORMERS_CACHE = "F:\huggingface\models\hub"
    $env:HF_ASSETS_CACHE = "F:\huggingface\models\assets"
    $env:HF_XET_CACHE = "F:\huggingface\models\xet"
    $env:TORCH_HOME = "F:\huggingface\models\torch"
    $env:XDG_CACHE_HOME = "F:\huggingface\models\xdg_cache"
    $env:PIP_CACHE_DIR = "F:\huggingface\models\pip_cache"
    $env:CUDA_CACHE_PATH = "F:\huggingface\models\cuda_cache"
    $env:TORCH_EXTENSIONS_DIR = "F:\huggingface\models\torch_extensions"
    $env:TORCHINDUCTOR_CACHE_DIR = "F:\huggingface\models\torch_inductor"
    $env:TRITON_CACHE_DIR = "F:\huggingface\models\triton"
    $env:MPLCONFIGDIR = "F:\huggingface\models\matplotlib"
    $env:NUMBA_CACHE_DIR = "F:\huggingface\models\numba_cache"
    $env:OLLAMA_MODELS = "F:\ollama\models"
    $env:TEMP = Join-Path $RepoRoot "runtime\codex_temp"
    $env:TMP = Join-Path $RepoRoot "runtime\codex_temp"
    $env:TMPDIR = Join-Path $RepoRoot "runtime\codex_temp"
    $env:COMPANION_USE_MOCK_TEXT = "0"
    $env:COMPANION_USE_MOCK_IMAGE = "0"
    $env:COMPANION_PRELOAD_TEXT_MODEL = "0"
    $env:COMPANION_STOP_OLLAMA_BEFORE_IMAGE = "1"
    $env:COMPANION_SMOKE_RESOLUTION_PRESET = $ResolutionPreset
    $env:COMPANION_SMOKE_SLUG = $SmokeSlug
}

function Stop-CompanionProcesses {
    $targets = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "ollama.exe") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -match "stable-diffusion-webui|launch.py|smoke_real_app_route_image") -or
        ($_.Name -eq "cmd.exe" -and $_.CommandLine -match "webui-user.bat")
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

function Remove-SmokeDbRows {
    $cleanupCode = @'
import sqlite3
from pathlib import Path

db_path = Path(r"F:\projects\perchance_clone\perchance_clone\runtime\companion_v1_app.sqlite3")
slug = "codex-echidna-real-route-smoke"
if db_path.exists():
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id FROM characters WHERE slug = ?", (slug,)).fetchone()
        if row:
            character_id = int(row["id"])
            conn.execute("DELETE FROM image_requests WHERE character_id = ?", (character_id,))
            conn.execute(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE character_id = ?)",
                (character_id,),
            )
            conn.execute("DELETE FROM conversations WHERE character_id = ?", (character_id,))
            conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
            print(f"[cleanup] removed smoke DB character id={character_id}")
        else:
            print("[cleanup] no smoke DB rows found")
'@
    $cleanupCode = $cleanupCode.Replace('slug = "codex-echidna-real-route-smoke"', ('slug = "{0}"' -f $SmokeSlug))
    try {
        $cleanupCode | & $PythonExe -
    }
    catch {
        Write-Host ("[cleanup] DB cleanup skipped: {0}" -f $_.Exception.Message)
    }
}

function Get-ResourceSnapshot {
    $os = Get-CimInstance Win32_OperatingSystem
    $commitCounters = Get-Counter "\Memory\Committed Bytes", "\Memory\Commit Limit"
    $commit = [double]$commitCounters.CounterSamples[0].CookedValue
    $limit = [double]$commitCounters.CounterSamples[1].CookedValue
    $gpuText = "0, 0"
    try {
        $gpuText = (& nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits).Trim()
    }
    catch {}
    $gpuParts = $gpuText -split ","
    [pscustomobject]@{
        Time = (Get-Date).ToString("s")
        FreeRamGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
        TotalRamGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        CommitGb = [math]::Round($commit / 1GB, 2)
        CommitLimitGb = [math]::Round($limit / 1GB, 2)
        CommitRatio = if ($limit -gt 0) { [math]::Round($commit / $limit, 3) } else { 0 }
        VramUsedMiB = [int]($gpuParts[0].Trim())
        VramFreeMiB = [int]($gpuParts[1].Trim())
    }
}

Set-FOnlyEnv
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "runtime\logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "runtime\codex_temp") | Out-Null

Write-Host "[guard] pre-clean"
Stop-CompanionProcesses
Start-Sleep -Seconds 3
$initial = Get-ResourceSnapshot
Write-Host ("[resources] start free_ram={0}GB commit={1}/{2}GB ratio={3} vram={4}/{5}MiB used/free" -f $initial.FreeRamGb, $initial.CommitGb, $initial.CommitLimitGb, $initial.CommitRatio, $initial.VramUsedMiB, $initial.VramFreeMiB)
Write-Host ("[guard] resolution_preset='{0}'" -f $ResolutionPreset)
Write-Host ("[guard] smoke_script='{0}' slug='{1}'" -f $SmokeScriptRel, $SmokeSlug)

$watchdogScript = {
    param($RepoRoot, $LogPath, $MinFreeRamGb, $MaxCommitRatio, $MaxVramUsedMiB, $PollSeconds)

    function Stop-CompanionProcessesInner {
        $targets = Get-CimInstance Win32_Process | Where-Object {
            ($_.Name -eq "ollama.exe") -or
            ($_.Name -eq "python.exe" -and $_.CommandLine -match "stable-diffusion-webui|launch.py|smoke_real_app_route_image") -or
            ($_.Name -eq "cmd.exe" -and $_.CommandLine -match "webui-user.bat")
        }
        foreach ($p in $targets) {
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
        }
    }

    while ($true) {
        try {
            $os = Get-CimInstance Win32_OperatingSystem
            $commitCounters = Get-Counter "\Memory\Committed Bytes", "\Memory\Commit Limit"
            $commit = [double]$commitCounters.CounterSamples[0].CookedValue
            $limit = [double]$commitCounters.CounterSamples[1].CookedValue
            $freeRamGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
            $commitRatio = if ($limit -gt 0) { $commit / $limit } else { 0 }
            $vramUsed = 0
            try {
                $gpuText = (& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits).Trim()
                $vramUsed = [int]$gpuText
            }
            catch {}
            $line = "[{0}] free_ram={1}GB commit_ratio={2:n3} vram_used={3}MiB" -f (Get-Date).ToString("s"), $freeRamGb, $commitRatio, $vramUsed
            Add-Content -Path $LogPath -Value $line
            if ($freeRamGb -lt $MinFreeRamGb -or $commitRatio -gt $MaxCommitRatio -or $vramUsed -gt $MaxVramUsedMiB) {
                Add-Content -Path $LogPath -Value ("[GUARD TRIPPED] " + $line)
                Stop-CompanionProcessesInner
                exit 77
            }
        }
        catch {
            Add-Content -Path $LogPath -Value ("[watchdog error] " + $_.Exception.Message)
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

$watchdog = Start-Job -ScriptBlock $watchdogScript -ArgumentList $RepoRoot, $WatchdogLog, $MinFreeRamGb, $MaxCommitRatio, $MaxVramUsedMiB, $PollSeconds
$exitCode = 1
try {
    Push-Location $RepoRoot
    try {
        & $PythonExe $SmokeScript
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($watchdog.State -eq "Running") {
        Stop-Job $watchdog -ErrorAction SilentlyContinue
    }
    Receive-Job $watchdog -ErrorAction SilentlyContinue | Out-Host
    Remove-Job $watchdog -Force -ErrorAction SilentlyContinue
    Write-Host "[guard] final cleanup"
    Stop-CompanionProcesses
    Remove-SmokeDbRows
    Start-Sleep -Seconds 4
    $final = Get-ResourceSnapshot
    Write-Host ("[resources] final free_ram={0}GB commit={1}/{2}GB ratio={3} vram={4}/{5}MiB used/free" -f $final.FreeRamGb, $final.CommitGb, $final.CommitLimitGb, $final.CommitRatio, $final.VramUsedMiB, $final.VramFreeMiB)
    Write-Host "[watchdog log] $WatchdogLog"
}

if ($exitCode -ne 0) {
    throw "Guarded real app route smoke failed with exit code $exitCode"
}
