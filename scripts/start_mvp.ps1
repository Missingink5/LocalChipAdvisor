param(
    [string]$Manifest = "",
    [int]$Port = 8501
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\python.exe"
if (-not $Manifest) { $Manifest = Join-Path $projectRoot "data\mvp\demo-v2\manifest.json" }
if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Missing interpreter: $pythonExe" }
if (-not (Test-Path -LiteralPath $Manifest)) {
    throw "Missing MVP manifest: $Manifest. Build the index first; see docs/MVP_RUNBOOK.md."
}
$Manifest = (Resolve-Path -LiteralPath $Manifest).Path
# Run in a child PowerShell because the existing helper calls exit.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "start_ollama.ps1")
if ($LASTEXITCODE -ne 0) { throw "Local Ollama startup failed." }
Set-Location -LiteralPath $projectRoot
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
Write-Host "Open http://127.0.0.1:$Port ; press Ctrl+C to stop."
& $pythonExe -m streamlit run (Join-Path $projectRoot "mvp_app.py") --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false -- --manifest $Manifest
exit $LASTEXITCODE
