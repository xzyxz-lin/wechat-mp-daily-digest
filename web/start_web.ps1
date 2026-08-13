[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8032,

    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$localHostAddress = '127.0.0.1'
$webUrl = "http://${localHostAddress}:$Port/"
$serverScript = Join-Path -Path $PSScriptRoot -ChildPath 'paper_observatory.py'
$venvPython = Join-Path -Path $PSScriptRoot -ChildPath '..\scripts\.venv\Scripts\python.exe'

function Test-PaperObservatoryReady {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($Url + 'api/health') -TimeoutSec 1
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $serverScript)) {
    throw "Paper Observatory server script not found: $serverScript"
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Python venv not found: $venvPython"
}

if (-not (Test-PaperObservatoryReady -Url $webUrl)) {
    Start-Process -FilePath $venvPython -ArgumentList @($serverScript, '--host', '0.0.0.0', '--port', [string]$Port) -WindowStyle Hidden | Out-Null

    $ready = $false
    foreach ($attempt in 1..40) {
        Start-Sleep -Milliseconds 250
        if (Test-PaperObservatoryReady -Url $webUrl) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw 'Paper Observatory local service startup timed out.'
    }
}

if (-not $NoBrowser) {
    Start-Process -FilePath $webUrl | Out-Null
}
