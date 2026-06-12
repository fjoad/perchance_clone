param(
    [string]$CharacterFile = "characters\atago.txt",
    [int]$Width = 704,
    [int]$Height = 704,
    [double]$HrScale = 2.0,
    [int]$Steps = 20,
    [int]$HrSecondPassSteps = 20,
    [double]$Cfg = 7.0,
    [double]$Denoise = 0.7,
    [string]$SamplerName = "DPM++ 2M",
    [string]$Scheduler = "Automatic",
    [string]$HrUpscaler = "Latent",
    [string]$TextModel = "hf.co/dphn/Dolphin-X1-8B-GGUF:Q5_K_M",
    [int]$NumPredict = 520,
    [ValidateSet("app_current", "direct_vn_v2")]
    [string]$PromptStyle = "app_current",
    [ValidateSet("current_labeled", "strict_json", "deterministic_template", "visual_fields_json")]
    [string]$ImagePromptStrategy = "current_labeled"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$A1111Root = "F:\projects\a1111\stable-diffusion-webui"
$PythonExe = "F:\anaconda3\envs\companion_v1\python.exe"

function Set-FOnlyEnv {
    $env:HF_HOME = "F:\huggingface\models"
    $env:HF_HUB_CACHE = "F:\huggingface\models\hub"
    $env:HUGGINGFACE_HUB_CACHE = "F:\huggingface\models\hub"
    $env:TRANSFORMERS_CACHE = "F:\huggingface\models\hub"
    $env:TORCH_HOME = "F:\torch"
    $env:XDG_CACHE_HOME = "F:\cache"
    $env:OLLAMA_MODELS = "F:\ollama\models"
    $env:TEMP = Join-Path $RepoRoot "runtime\temp"
    $env:TMP = Join-Path $RepoRoot "runtime\temp"
}

function Stop-BenchmarkProcesses {
    $targets = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "ollama.exe") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -match "stable-diffusion-webui|bench_production_flow_a1111|launch.py") -or
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

function Wait-A1111Ready {
    $deadline = (Get-Date).AddMinutes(6)
    do {
        Start-Sleep -Seconds 5
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:7860/sdapi/v1/options" -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                Write-Host "[a1111] ready"
                return
            }
        }
        catch {
            Write-Host "[a1111] waiting..."
        }
    } while ((Get-Date) -lt $deadline)
    throw "A1111 did not become ready within 6 minutes."
}

function Print-Resources($Label) {
    $gpu = (& nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits).Trim()
    $os = Get-CimInstance Win32_OperatingSystem
    $freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    $totalGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    Write-Host ("[resources] {0}: gpu={1} MiB used/free, ram_free={2}/{3} GiB" -f $Label, $gpu, $freeGb, $totalGb)
}

Set-FOnlyEnv
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "runtime\temp") | Out-Null

Write-Host "[safe-runner] pre-clean"
Stop-BenchmarkProcesses
Start-Sleep -Seconds 3
Print-Resources "after pre-clean"

try {
    Write-Host "[a1111] starting"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "webui-user.bat" -WorkingDirectory $A1111Root -WindowStyle Hidden
    Wait-A1111Ready

    $benchArgs = @(
        "scripts\bench_production_flow_a1111.py",
        "--character-file", $CharacterFile,
        "--width", "$Width",
        "--height", "$Height",
        "--hr-scale", "$HrScale",
        "--steps", "$Steps",
        "--hr-second-pass-steps", "$HrSecondPassSteps",
        "--cfg", "$Cfg",
        "--denoise", "$Denoise",
        "--sampler-name", $SamplerName,
        "--scheduler", $Scheduler,
        "--hr-upscaler", $HrUpscaler,
        "--text-model", $TextModel,
        "--num-predict", "$NumPredict",
        "--prompt-style", $PromptStyle,
        "--image-prompt-strategy", $ImagePromptStrategy
    )

    Write-Host "[benchmark] $PythonExe $($benchArgs -join ' ')"
    Push-Location $RepoRoot
    try {
        & $PythonExe @benchArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Benchmark failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Write-Host "[safe-runner] final cleanup"
    Stop-BenchmarkProcesses
    Start-Sleep -Seconds 4
    Print-Resources "after final cleanup"
}
