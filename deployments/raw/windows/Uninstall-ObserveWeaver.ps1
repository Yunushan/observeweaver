#Requires -Version 5.1
# SPDX-License-Identifier: 0BSD

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$InstallRoot = 'C:\ObserveWeaver',
    [switch]$RemoveData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

foreach ($serviceName in @('prometheus', 'alertmanager')) {
    $wrapper = Join-Path $InstallRoot "services\$serviceName\$serviceName.exe"
    if (Test-Path -LiteralPath $wrapper) {
        if ($PSCmdlet.ShouldProcess($serviceName, 'Stop and uninstall Windows service')) {
            & $wrapper stop 2>$null
            & $wrapper uninstall
        }
    }
}

$openSearchServiceScript = Get-ChildItem `
    -Path $InstallRoot `
    -Filter opensearch-service.bat `
    -Recurse `
    -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if (
    $null -ne $openSearchServiceScript -and
    $PSCmdlet.ShouldProcess('OpenSearch', 'Stop and uninstall Windows service')
) {
    & $openSearchServiceScript stop 2>$null
    & $openSearchServiceScript remove
}

$uninstallRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($displayNamePattern in @('*OpenTelemetry Collector*', '*Grafana*')) {
    $product = Get-ItemProperty -Path $uninstallRoots -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like $displayNamePattern } |
        Select-Object -First 1
    if ($null -ne $product -and $PSCmdlet.ShouldProcess($product.DisplayName, 'Uninstall MSI')) {
        $productCode = Split-Path -Leaf $product.PSPath
        $process = Start-Process msiexec.exe `
            -ArgumentList @('/x', $productCode, '/qn', '/norestart') `
            -Wait `
            -PassThru
        if ($process.ExitCode -notin @(0, 1605, 3010)) {
            throw "MSI uninstall failed with exit code $($process.ExitCode)."
        }
    }
}

if ($RemoveData) {
    if ($PSCmdlet.ShouldProcess($InstallRoot, 'Permanently remove programs, configuration, and data')) {
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force
    }
}
else {
    Write-Output "Services removed. Data remains under $InstallRoot."
}
