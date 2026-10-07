$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:HF_HOME = Join-Path $PSScriptRoot 'data\models\hf-cache'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot 'data\browsers'
$env:TEMP = Join-Path $PSScriptRoot 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required.' }
    & $runtime -m pip install --cache-dir .\tmp\pip-cache -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
Write-Host 'Open http://127.0.0.1:8766 in your browser. Ctrl+C stops the server.'
& $runtime -m uvicorn app.main:app --host 127.0.0.1 --port 8766 --no-access-log
