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
$composeProject = 'paper-observatory-wewe'
$serverScript  = Join-Path -Path $PSScriptRoot -ChildPath 'paper_observatory.py'
$venvPython    = Join-Path -Path $projectRoot -ChildPath 'scripts\.venv\Scripts\python.exe'
$dockerDesktop = Join-Path -Path $env:LOCALAPPDATA -ChildPath 'Programs\DockerDesktop\Docker Desktop.exe'
$weweUrl = 'http://127.0.0.1:4000'
$siteUrl = "http://127.0.0.1:$Port"

function Test-PaperObservatoryReady {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ($Url + '/api/health') -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Test-WeWeReady {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri ($weweUrl + '/feeds/all.json') -TimeoutSec 2
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
# Always address this workspace's explicit Compose project.  Do not reuse a
# generic wewe-rss-app container, because another checkout can have the same
# default Compose name while mounting a different database directory.
if (-not (Test-Path -LiteralPath $composeFile)) {
    Write-Host "compose file missing: $composeFile"
    exit 1
}
Write-Host 'Starting Paper Observatory WeWe RSS container...'
& docker compose --project-name $composeProject -f $composeFile up -d | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'WeWe RSS container start failed.'
    exit 1
}
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    if (Test-WeWeReady) { $ok = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ok) {
    Write-Host 'WeWe RSS start timeout.'
    exit 1
}

# ---- Step 3: Web backend (重启以确保使用最新代码) ----
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "python venv missing: $venvPython"
    exit 1
}
# 若端口已被旧进程占用，先释放，避免用到旧代码（8032 专用于观察台）。
# Windows 下某些 Python 启动方式会留下父/子进程；只杀监听子进程会被父进程继续托管。
# 因此只匹配命令行明确属于本项目、且端口相同的 Python 进程，再一并停止。
$serverPattern = [regex]::Escape($serverScript)
$portPattern = "--port\s+$Port(\s|$)"
$oldServerProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and
    $_.CommandLine -match $serverPattern -and
    $_.CommandLine -match $portPattern
}
foreach ($oldServerProcess in $oldServerProcesses) {
    try { Stop-Process -Id $oldServerProcess.ProcessId -Force -ErrorAction Stop } catch {}
}
if ($oldServerProcesses) { Start-Sleep -Seconds 1 }
if (-not (Test-PaperObservatoryReady -Url $siteUrl)) {
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

# ---- Step 4: open browser (WeWe RSS dash + Paper Observatory) ----
$weweDash = 'http://localhost:4000/dash'
Write-Host "Ready: $siteUrl"
Write-Host "WeWe RSS: $weweDash"
if (-not $NoBrowser) {
    Start-Process explorer.exe -ArgumentList $weweDash | Out-Null
    Start-Process explorer.exe -ArgumentList $siteUrl | Out-Null
    Write-Host 'Two tabs opened: WeWe RSS (for scan/enable) + Paper Observatory. Close in 3s...'
    Start-Sleep -Seconds 3
}
