# watchdog.ps1 - Restart the Telegram bot if it is not running.
# Scheduled to run every 5 minutes via Windows Task Scheduler.

$LogFile   = "C:\Dialog-podcast\logs\watchdog.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-Log {
    param([string]$Message)
    $line = "$Timestamp  $Message"
    Write-Output $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8

    # Trim to last 1000 lines
    $lines = Get-Content $LogFile -ErrorAction SilentlyContinue
    if ($lines -and $lines.Count -gt 1000) {
        $lines | Select-Object -Last 1000 | Set-Content $LogFile -Encoding UTF8
    }
}

# Ensure log directory exists
$null = New-Item -ItemType Directory -Path (Split-Path $LogFile) -Force

# Check if telegram_bot.py is running
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*telegram_bot*" }

if ($procs) {
    $pid0 = ($procs | Select-Object -First 1).ProcessId
    Write-Log "OK      - bot is running (PID $pid0)"
    exit 0
}

Write-Log "DEAD    - bot process not found, restarting..."

# Load API keys from User-level environment (not stored in .env)
$env:ANTHROPIC_API_KEY  = [System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY",  "User")
$env:OPENAI_API_KEY     = [System.Environment]::GetEnvironmentVariable("OPENAI_API_KEY",     "User")
$env:ELEVENLABS_API_KEY = [System.Environment]::GetEnvironmentVariable("ELEVENLABS_API_KEY", "User")

# Load bot-specific vars from .env (TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS, etc.)
$EnvFile = "C:\Dialog-podcast\.env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^([^#][^=]*)=(.+)") {
            $key = $Matches[1].Trim()
            $val = $Matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            Set-Item "Env:$key" $val
        }
    }
}

# Start the bot hidden; bot.log written by the FileHandler inside telegram_bot.py
$proc = Start-Process -FilePath "pythonw.exe" `
    -ArgumentList "-u telegram_bot.py" `
    -WorkingDirectory "C:\Dialog-podcast" `
    -WindowStyle Hidden `
    -PassThru

if ($proc) {
    Write-Log "STARTED - new bot PID $($proc.Id)"
} else {
    Write-Log "ERROR   - Start-Process returned null"
}
