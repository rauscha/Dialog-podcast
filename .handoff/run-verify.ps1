# Overnight verify-run wrapper.
# Sequentially runs all three digest shows with SKIP_GIT=1.
# host_memory.json and feed-*.xml will be modified in working tree but NOT pushed.
# Each show's output is appended to .handoff/verify-run.log so we can read it after.

$ErrorActionPreference = 'Continue'

# Load .env, skipping comments and empty lines, then force SKIP_GIT=1.
Get-Content .env | ForEach-Object {
    if ($_ -notmatch '^\s*#' -and $_ -match '=') {
        $k, $v = $_ -split '=', 2
        if ($k.Trim()) {
            [Environment]::SetEnvironmentVariable($k.Trim(), $v)
        }
    }
}
$env:SKIP_GIT = '1'

$log = '.handoff/verify-run.log'
"=== VERIFY RUN START $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -Append $log -Encoding utf8

$shows = 'mfm', 'fetal', 'ai'
foreach ($s in $shows) {
    $start = Get-Date
    "=== START $s @ $($start.ToString('HH:mm:ss')) ===" | Out-File -Append $log -Encoding utf8
    & python generate_podcast.py --digest $s 2>&1 | Out-File -Append $log -Encoding utf8
    $exit = $LASTEXITCODE
    $end = Get-Date
    $dur = [int]($end - $start).TotalSeconds
    if ($exit -eq 0) {
        "=== END $s OK (${dur}s) @ $($end.ToString('HH:mm:ss')) ===" | Out-File -Append $log -Encoding utf8
    } else {
        "=== END $s FAILED exit=$exit (${dur}s) @ $($end.ToString('HH:mm:ss')) ===" | Out-File -Append $log -Encoding utf8
    }
}
"=== ALL VERIFY RUNS DONE $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -Append $log -Encoding utf8
