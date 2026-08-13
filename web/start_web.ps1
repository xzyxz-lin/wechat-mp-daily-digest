[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8032,

    [switch]$NoBrowser
)

$ErrorActionPreference = 'Continue'

# ---- Paths (kept literal so PS5.1 reads them correctly) ----
$dockerDesktop = Join-Path -Path $env:LOCALAPPDATA -ChildPath 'Programs\DockerDesktop\Docker Desktop.exe'
$composeFile   = 'A:\workbuddy项目\推送公众号论文\wewe-rss\docker-compose.sqlite.yml'
$weweUrl       = 'http://127.0.0.1:4000'
$serverScript  = Join-Path -Path $PSScriptRoot -ChildPath 'paper_observatory.py'
$venvPython    = Join-Path -Path $PSScriptRoot -ChildPath '..\scripts\.venv\Scripts\python.exe'
$siteUrl       = "http://127.0.0.1:$Port"

# ---- Helpers ----
function Test-PaperObservatoryReady {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($Url + 'api/health') -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch { return $false }
}

function Test-WeWeReady {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ($weweUrl + 'feeds/all.json') -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Wait-DockerEngine {
    param([int]$TimeoutSec = 120)
    for ($i = 0; $i -lt $TimeoutSec; $i++) {
        $ver = & docker info --format '{{.ServerVersion}}' 2>$null
        if ($ver) {
            Write-Host "Docker engine ready: $ver"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Wait-WeWe {
    param([int]$TimeoutSec = 60)
    for ($i = 0; $i -lt $TimeoutSec; $i++) {
        if (Test-WeWeReady) {
            Write-Host 'WeWe RSS ready'
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

# ---- Step 1: Docker Desktop engine ----
$dockerVer = & docker info --format '{{.ServerVersion}}' 2>$null
if ($dockerVer) {
    Write-Host "Docker already running: $dockerVer"
} else {
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        Write-Host "Docker Desktop not found at: $dockerDesktop"
        Write-Host 'Please open Docker Desktop manually once.'
        exit 1
    }
    Write-Host 'Docker Desktop not running, starting...'
    Start-Process -FilePath $dockerDesktop | Out-Null
    $ok = Wait-DockerEngine -TimeoutSec 120
    if (-not $ok) {
        Write-Host 'Docker engine failed to start within 120s.'
        exit 1
    }
}

# ---- Step 2: WeWe RSS container ----
$weweName = & docker ps --filter 'name=wewe-rss-app' --format '{{.Names}}' 2>$null
if ($weweName) {
    Write-Host "WeWe RSS container already running: $weweName"
} else {
    if (-not (Test-Path -LiteralPath $composeFile)) {
        Write-Host "docker-compose file not found: $composeFile"
        exit 1
    }
    Write-Host 'Starting WeWe RSS container...'
    & docker compose -f $composeFile up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "docker compose up failed (exit=$LASTEXITCODE)"
        exit 1
    }
    $ok = Wait-WeWe -TimeoutSec 60
    if (-not $ok) {
        Write-Host 'WeWe RSS failed to respond within 60s.'
        exit 1
    }
}

# ---- Step 3: Web backend ----
if (-not (Test-Path -LiteralPath $serverScript)) {
    Write-Host "Backend script missing: $serverScript"
    exit 1
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Python venv missing: $venvPython"
    exit 1
}

if (-not (Test-PaperObservatoryReady -Url $siteUrl)) {
    Write-Host 'Starting Paper Observatory backend...'
    Start-Process -FilePath $venvPython -ArgumentList @($serverScript, '--host', '0.0.0.0', '--port', [string]$Port) -WindowStyle Hidden | Out-Null

    $ready = $false
    foreach ($attempt in 1..40) {
        Start-Sleep -Milliseconds 250
        if (Test-PaperObservatoryReady -Url $siteUrl) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        Write-Host 'Paper Observatory backend failed to start within 10s.'
        exit 1
    }
}

Write-Host "Paper Observatory ready at $siteUrl"
if (-not $NoBrowser) {
    Start-Process -FilePath $siteUrl | Out-Null
}