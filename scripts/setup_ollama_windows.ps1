param(
    [string]$Model = "qwen3:14b",
    [string]$ModelDir = "",
    [switch]$Install,
    [switch]$Pull,
    [switch]$Start,
    [switch]$ConfigureRepo,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

function Write-Step($Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Find-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $local = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $local) {
        $env:Path = "$(Split-Path $local);$env:Path"
        return $local
    }
    return $null
}

function Test-OllamaApi {
    try {
        Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if ($Help) {
    @"
Ollama local service setup helper

Examples:
  .\scripts\setup_ollama_windows.ps1 -Install -Start -Pull -ConfigureRepo -Model qwen3:14b
  .\scripts\setup_ollama_windows.ps1 -Start -Pull -Model qwen3:30b
  .\scripts\setup_ollama_windows.ps1 -ConfigureRepo -Model qwen3:14b

Flags:
  -Install        Try winget install Ollama.Ollama if ollama is missing.
  -Start          Start `ollama serve` in a hidden background process if the API is down.
  -Pull           Pull the requested model with `ollama pull`.
  -ConfigureRepo  Set config.json dialogue_model to ollama:<model>.
  -ModelDir       Set user OLLAMA_MODELS before starting/pulling.
"@ | Write-Host
    exit 0
}

Write-Step "Checking Ollama installation"

if ($ModelDir) {
    $resolvedModelDir = [System.IO.Path]::GetFullPath($ModelDir)
    New-Item -ItemType Directory -Force -Path $resolvedModelDir | Out-Null
    [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $resolvedModelDir, "User")
    $env:OLLAMA_MODELS = $resolvedModelDir
    Write-Host "OLLAMA_MODELS set for this shell and your user account: $resolvedModelDir"
}

$ollama = Find-Ollama
if (-not $ollama -and $Install) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "winget was not found. Install Ollama from https://ollama.com/download, then rerun this script."
    }
    Write-Step "Installing Ollama with winget"
    winget install --id Ollama.Ollama -e --source winget
    $ollama = Find-Ollama
}

if (-not $ollama) {
    throw "Ollama is not installed or not on PATH. Install it from https://ollama.com/download or rerun with -Install."
}

Write-Host "Ollama executable: $ollama"

if ($Start -and -not (Test-OllamaApi)) {
    Write-Step "Starting Ollama API server"
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
    $ready = $false
    foreach ($attempt in 1..20) {
        Start-Sleep -Seconds 1
        if (Test-OllamaApi) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw "Ollama did not answer on http://127.0.0.1:11434 after 20 seconds."
    }
}

if (Test-OllamaApi) {
    Write-Host "Ollama API is reachable at http://127.0.0.1:11434"
} else {
    Write-Warning "Ollama API is not reachable. Use -Start or launch Ollama from the Start menu."
}

if ($Pull) {
    Write-Step "Pulling model $Model"
    & $ollama pull $Model
}

if ($ConfigureRepo) {
    Write-Step "Configuring repo for Ollama dialogue passes"
    $configPath = Join-Path $RepoRoot "config.json"
    $config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
    $config.dialogue_model = "ollama:$Model"
    $config.local_llm_provider = "ollama"
    $config.local_llm_base_url = "http://127.0.0.1:11434"
    $config.local_llm_timeout_sec = 3600
    $config.local_llm_num_ctx = 32768
    $config.local_llm_keep_alive = "30m"
    $config.local_llm_think = $false
    $json = $config | ConvertTo-Json -Depth 30
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($configPath, $json + [Environment]::NewLine, $utf8NoBom)
    Write-Host "Updated config.json dialogue_model to ollama:$Model"
    Write-Host "Research and fact-check models were left on their existing routes."
}

Write-Step "Smoke-test command"
Write-Host "python scripts\ollama_smoke_test.py --model $Model"
