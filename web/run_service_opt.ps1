# Paper Observatory - Reversible Service Optimization (admin required)
# This script ONLY: set services to Manual, disable HKLM autostart, disable scheduled tasks.
# It does NOT delete anything. All changes are reversible.
$ErrorActionPreference = 'Continue'
$log = @()
$log += "=== Optimization script started: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + " ==="

# ---- 1. Services to Manual ----
$svcManual = @('W3SVC','MSMQ','NetMsmqActivator','Autodesk CER Service')
foreach ($name in $svcManual) {
    try {
        Set-Service -Name $name -StartupType Manual -ErrorAction Stop
        $log += "OK   service->Manual : $name"
    } catch {
        $log += "FAIL service->Manual : $name :: " + $_.Exception.Message
    }
}

# ---- 2. HKLM autostart: rename value (keep data, disable autostart) ----
function Disable-RunValueTrim($path, $matchName) {
    $prop = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue
    if (-not $prop) { $log += "SKIP autostart (key not found): $path"; return }
    $names = $prop.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } | Select-Object -ExpandProperty Name
    $target = $names | Where-Object { $_.TrimEnd() -eq $matchName } | Select-Object -First 1
    if ($target) {
        $newName = $target + '__DISABLED_BY_OPT'
        try {
            Rename-ItemProperty -Path $path -Name $target -NewName $newName -ErrorAction Stop
            $log += "OK   autostart->disabled : [$target]"
        } catch {
            $log += "FAIL autostart->disabled : [$target] :: " + $_.Exception.Message
        }
    } else {
        $log += "SKIP autostart (not found): $matchName"
    }
}

Disable-RunValueTrim 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' 'Autodesk Access Service'
Disable-RunValueTrim 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run' 'Autodesk Genuine Service'

# ---- 3. Scheduled tasks: disable (do NOT delete) ----
$tasks = @(
    'OneDrive Startup Task-S-1-5-21-662924492-3609936775-2051179329-1001',
    'OneDrive Reporting Task-S-1-5-21-662924492-3609936775-2051179329-1001',
    'OneDrive Per-Machine Standalone Update Task'
)
foreach ($t in $tasks) {
    try {
        Disable-ScheduledTask -TaskName $t -TaskPath '\' -ErrorAction Stop | Out-Null
        $log += "OK   task->disabled : $t"
    } catch {
        $log += "FAIL task->disabled : $t :: " + $_.Exception.Message
    }
}

$log += "=== Optimization script finished ==="
$log -join "`r`n" | Out-File -Encoding UTF8 'A:\workbuddy项目\论文观察台\.workbuddy\opt_result.txt'
Write-Output ($log -join "`r`n")
Write-Output ""
Write-Output "DONE - check opt_result.txt for details"
