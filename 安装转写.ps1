$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:TEMP = Join-Path $PSScriptRoot 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
& .\.venv\Scripts\python.exe -m pip install --cache-dir .\tmp\pip-cache 'faster-whisper>=1.1,<2'
if ($LASTEXITCODE -ne 0) { throw 'Transcription dependency installation failed.' }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    & .\.venv\Scripts\python.exe -m pip install --cache-dir .\tmp\pip-cache -r requirements-gpu.txt
    if ($LASTEXITCODE -ne 0) { throw 'GPU runtime installation failed; CPU transcription remains available.' }
}
Write-Host 'Transcription installed. Videos automatically use platform subtitles, then local speech recognition.'
