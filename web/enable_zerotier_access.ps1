[CmdletBinding()]
param(
    [string]$LocalZeroTierAddress = '10.44.55.169',

    [string]$RemoteAddresses = '10.44.55.0/24',

    [int]$Port = 8032
)

# 公众号论文观察台 - 开放 ZeroTier 局域网访问
# 用法（需管理员）：powershell -ExecutionPolicy Bypass -File enable_zerotier_access.ps1

$ErrorActionPreference = 'Stop'

$currentPrincipal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '请以管理员身份运行此脚本（需要更新 Windows 防火墙）'
}

$ruleName = "Paper Observatory ZeroTier $Port"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Set-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Enabled True -Profile Any -ErrorAction Stop | Out-Null
    Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $existing -LocalAddress $LocalZeroTierAddress -RemoteAddress $RemoteAddresses -ErrorAction Stop | Out-Null
    Write-Host "已更新防火墙规则: $ruleName" -ForegroundColor Green
}
else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Enabled True `
        -Protocol TCP -LocalPort $Port -LocalAddress $LocalZeroTierAddress `
        -RemoteAddress $RemoteAddresses -Profile Any -ErrorAction Stop | Out-Null
    Write-Host "已创建防火墙规则: $ruleName" -ForegroundColor Green
}

Write-Host ""
Write-Host "局域网访问地址: http://${LocalZeroTierAddress}:$Port" -ForegroundColor Cyan
Write-Host "允许来源: $RemoteAddresses" -ForegroundColor Yellow
Write-Host ""
Write-Host "说明：后端需以 --host 0.0.0.0 启动（start_web.ps1 已默认如此）。" -ForegroundColor DarkGray
