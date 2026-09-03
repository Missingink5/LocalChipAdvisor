$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\python.exe"
$ollamaExe = Join-Path $projectRoot "runtime\Ollama\ollama.exe"

Write-Output "Project root: $projectRoot"
& $pythonExe --version
& $ollamaExe --version

$version = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 5
Write-Output "Ollama API: $($version.version) at 127.0.0.1:11434"

$listenerLines = @(& netstat -ano -p TCP | Select-String -Pattern ':11434\s+.*LISTENING')
if (-not $listenerLines) {
    throw "No TCP listener found on port 11434."
}

foreach ($line in $listenerLines) {
    $text = $line.ToString().Trim()
    Write-Output "Listener: $text"
    if ($text -notmatch '^TCP\s+(127\.0\.0\.1|\[::1\]):11434\s+') {
        throw "Ollama is listening outside localhost: $text"
    }
}
