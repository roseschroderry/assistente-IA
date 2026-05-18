$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$outLog = Join-Path $root "server.out.log"

Remove-Item $outLog -ErrorAction SilentlyContinue

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8008 2>&1 | Tee-Object -FilePath $outLog
