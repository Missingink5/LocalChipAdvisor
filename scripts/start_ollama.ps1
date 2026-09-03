$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$ollamaExe = Join-Path $projectRoot "runtime\Ollama\ollama.exe"
$modelDir = Join-Path $projectRoot "models\ollama"
$logDir = Join-Path $projectRoot "logs"

if (-not (Test-Path -LiteralPath $ollamaExe)) {
    throw "Ollama executable not found: $ollamaExe"
}

New-Item -ItemType Directory -Path $modelDir, $logDir -Force | Out-Null

try {
    $version = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2
    Write-Output "Ollama is already running on 127.0.0.1:11434 (version $($version.version))."
    exit 0
} catch {
    # Expected when the local service has not started yet.
}

$env:OLLAMA_MODELS = $modelDir
$env:OLLAMA_HOST = "127.0.0.1:11434"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_CONTEXT_LENGTH = "4096"

$process = Start-Process `
    -FilePath $ollamaExe `
    -ArgumentList "serve" `
    -WorkingDirectory (Split-Path -Parent $ollamaExe) `
    -WindowStyle Hidden `
    -PassThru

$process.Id | Set-Content -LiteralPath (Join-Path $logDir "ollama.pid")

for ($attempt = 1; $attempt -le 30; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $version = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2
        Write-Output "Ollama started on 127.0.0.1:11434 (version $($version.version), PID $($process.Id))."
        exit 0
    } catch {
        if ($process.HasExited) {
            throw "Ollama exited before becoming healthy (exit code $($process.ExitCode))."
        }
    }
}

throw "Ollama did not become healthy within the startup window."
