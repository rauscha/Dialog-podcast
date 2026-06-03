# register_scheduled_task.ps1 — Run ONCE to register the daily digest task.
#
# Creates a Windows Task Scheduler entry that fires run_digests.ps1 at 05:00
# every day. generate_podcast.py --digest-all then applies per-show weekday
# gating (MFM on Monday, Fetal on Wednesday, AI on Friday).
#
# Requirements:
#   - Run this script as Administrator (or with task-creation rights).
#   - Python must be on PATH (or edit $pythonExe below with the full path).
#
# After registering, test immediately with:
#   Start-ScheduledTask -TaskName "Dialog-podcast-daily-digests"

$repoRoot   = $PSScriptRoot
$scriptPath = Join-Path $repoRoot "run_digests.ps1"
$taskName   = "Dialog-podcast-daily-digests"
$description = (
    "Daily digest episode generation for Asynchronous podcast " +
    "(MFM Rounds on Mon, The Fetal Frontier on Wed, Signal in the Scan on Fri). " +
    "Weekday gating is applied inside the script; safe to run daily."
)

if (-not (Test-Path $scriptPath)) {
    Write-Error "run_digests.ps1 not found at $scriptPath. Run this from the repo root."
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute   "powershell.exe" `
    -Argument  "-NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`"" `
    -WorkingDirectory $repoRoot

$trigger  = New-ScheduledTaskTrigger -Daily -At "05:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit    (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances     IgnoreNew

Register-ScheduledTask `
    -TaskName   $taskName `
    -Description $description `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Force

Write-Host ""
Write-Host "Task '$taskName' registered successfully."
Write-Host "It will run run_digests.ps1 daily at 05:00."
Write-Host ""
Write-Host "Test it now with:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
Write-Host ""
Write-Host "Check its last-run status with:"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$taskName' | Select-Object LastRunTime, LastTaskResult"
