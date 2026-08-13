[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8032,

    [switch]$NoBrowser
)

$ErrorActionPreference = 'Continue'

# Derive all paths from $PSScriptRoot at runtime (no non-ASCII literals,
# so PowerShell 5.1 reads this script correctly regardless of encoding).
$projectRoot   = (Resolve-Path -LiteralPath (Join-Path -Path $PSScriptRoot -ChildPath '..')).Path
$composeFile   = Join-Path -Path $projectRoot -ChildPath 'wewe-rss\docker-compose.sqlite.yml'
$serverScript  = Join-Path -Path $PSScriptRoot -ChildPath 'paper_observatory.py'
$venvPython    = Join-Path -Path $projectRoot -ChildPath 'scripts\.venv\Scripts\python.exe'
$dockerDesktop = Join-Path -Path $env:LOCALAPPDATA -ChildPath 'Programs\DockerDesktop\Docker Desktop.exe'
$weweUrl = 'http://127.0.0.1:4000'
$siteUrl = "http://127.0.0.1:$Port"

function Test-PaperObservatoryReady {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ($Url + 'api/health') -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Test-WeWeReady {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ($weweUrl + 'feeds/all.json') -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# ---- Step 1: Docker engine ----
$dockerVer = & docker info --format '{{.ServerVersion}}' 2>$null
if (-not $dockerVer) {
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        Write-Host 'Docker Desktop not found. Open it manually once.'
        exit 1
    }
    Write-Host 'Starting Docker Desktop...'
    Start-Process -FilePath $dockerDesktop | Out-Null
    $ok = $false
    for ($i = 0; $i -lt 120; $i++) {
        $dockerVer = & docker info --format '{{.ServerVersion}}' 2>$null
        if ($dockerVer) { $ok = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ok) {
        Write-Host 'Docker engine start timeout.'
        exit 1
    }
}

# ---- Step 2: WeWe RSS container ----
$weweName = & docker ps --filter 'name=wewe-rss-app' --format '{{.Names}}' 2>$null
if (-not $weweName) {
    if (-not (Test-Path -LiteralPath $composeFile)) {
        Write-Host "compose file missing: $composeFile"
        exit 1
    }
    Write-Host 'Starting WeWe RSS container...'
    & docker compose -f $composeFile up -d | Out-Null
    $ok = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-WeWeReady) { $ok = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ok) {
        Write-Host 'WeWe RSS start timeout.'
        exit 1
    }
}

# ---- Step 3: Web backend ----
if (-not (Test-PaperObservatoryReady -Url $siteUrl)) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "python venv missing: $venvPython"
        exit 1
    }
    Write-Host 'Starting Paper Observatory backend...'
    Start-Process -FilePath $venvPython -ArgumentList @($serverScript, '--host', '0.0.0.0', '--port', [string]$Port) -WindowStyle Hidden | Out-Null
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-PaperObservatoryReady -Url $siteUrl) { $ok = $true; break }
    }
    if (-not $ok) {
        Write-Host 'Backend start timeout.'
        exit 1
    }
}

# ---- Step 4: open browser ----
Write-Host "Ready: $siteUrl"
if (-not $NoBrowser) {
    Start-Process explorer.exe -ArgumentList $siteUrl | Out-Null
}