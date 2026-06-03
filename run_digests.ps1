# run_digests.ps1 — Daily digest runner, called by Windows Task Scheduler.
#
# generate_podcast.py --digest-all applies per-show weekday gating, so only
# shows due today (or due yesterday as a 1-day catch-up) actually run.
# Schedule this script once daily at 05:00 via register_scheduled_task.ps1.

Set-Location -Path $PSScriptRoot

# Load .env (skip comments and blank lines)
if (Test-Path .env) {
    Get-Content .env | ForEach-Object {
        if ($_ -notmatch '^\s*#' -and $_ -match '=') {
            $k, $v = $_ -split '=', 2
            [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
        }
    }
}

$env:PYTHONUTF8 = "1"

$stamp = (Get-Date -Format "yyyyMMdd_HHmmss")
$logFile = "logs\digest_scheduled_$stamp.log"
New-Item -ItemType Directory -Force -Path logs | Out-Null

Write-Host "[$stamp] Starting scheduled digest run -> $logFile"

python generate_podcast.py --digest-all --repo . 2>&1 | Tee-Object -FilePath $logFile

if ($LASTEXITCODE -ne 0) {
    Write-Host "Digest run exited $LASTEXITCODE. Check $logFile for details."
    exit $LASTEXITCODE
}

Write-Host "Digest run complete."
