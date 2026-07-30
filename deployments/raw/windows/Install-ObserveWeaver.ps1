#Requires -Version 5.1
# SPDX-License-Identifier: 0BSD

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$GeneratedEnvFile,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$SecretEnvFile,

    [string]$InstallRoot = 'C:\ObserveWeaver',

    [ValidateSet('Prometheus', 'Alertmanager', 'Grafana', 'OpenTelemetry', 'OpenSearch')]
    [string[]]$Components = @(),

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ForceRequested = $Force.IsPresent

function Import-DotEnv {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) {
            continue
        }
        $parts = $line.Split('=', 2)
        if ($parts.Count -eq 2) {
            $values[$parts[0].Trim()] = $parts[1]
        }
    }
    return $values
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this installer from an elevated PowerShell session.'
    }
}

function Get-Artifact {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][uri]$Uri,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Checksum,
        [ValidateSet('SHA256', 'SHA512')][string]$Algorithm = 'SHA256'
    )

    if ((Test-Path -LiteralPath $Destination) -and -not $script:ForceRequested) {
        $actual = (Get-FileHash -LiteralPath $Destination -Algorithm $Algorithm).Hash
        if ($actual -ne $Checksum) {
            throw "Checksum mismatch for cached artifact: $Destination"
        }
        return
    }
    if ($PSCmdlet.ShouldProcess($Uri.AbsoluteUri, "Download to $Destination")) {
        Invoke-WebRequest -Uri $Uri -OutFile $Destination -UseBasicParsing
        $actual = (Get-FileHash -LiteralPath $Destination -Algorithm $Algorithm).Hash
        if ($actual -ne $Checksum) {
            Remove-Item -LiteralPath $Destination -Force
            throw "Checksum mismatch for downloaded artifact: $($Uri.AbsoluteUri)"
        }
    }
}

function Expand-Artifact {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][string]$Archive,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if ((Test-Path -LiteralPath $Destination) -and -not $script:ForceRequested) {
        return
    }
    if ($PSCmdlet.ShouldProcess($Archive, "Extract to $Destination")) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
    }
}

function Install-WinSWService {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$WinSWSource
    )

    $serviceRoot = Join-Path $InstallRoot "services\$Name"
    $wrapper = Join-Path $serviceRoot "$Name.exe"
    $configuration = Join-Path $serviceRoot "$Name.xml"
    $logRoot = Join-Path $InstallRoot "logs\$Name"

    if ($PSCmdlet.ShouldProcess($Name, 'Install or update Windows service')) {
        New-Item -ItemType Directory -Path $serviceRoot -Force | Out-Null
        New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
        Copy-Item -LiteralPath $WinSWSource -Destination $wrapper -Force
        @"
<service>
  <id>$Name</id>
  <name>ObserveWeaver $Name</name>
  <description>Managed by ObserveWeaver.</description>
  <executable>$Executable</executable>
  <arguments>$Arguments</arguments>
  <workingdirectory>$WorkingDirectory</workingdirectory>
  <startmode>Automatic</startmode>
  <onfailure action="restart" delay="10 sec"/>
  <resetfailure>1 hour</resetfailure>
  <logpath>$logRoot</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
</service>
"@ | Set-Content -LiteralPath $configuration -Encoding UTF8
        & $wrapper stop 2>$null
        & $wrapper install
        & $wrapper start
    }
}

$generated = Import-DotEnv -Path $GeneratedEnvFile
$secrets = Import-DotEnv -Path $SecretEnvFile
$componentFlags = [ordered]@{
    Prometheus = 'PROMETHEUS_ENABLED'
    Alertmanager = 'ALERTMANAGER_ENABLED'
    Grafana = 'GRAFANA_ENABLED'
    OpenTelemetry = 'OTELCOL_ENABLED'
    OpenSearch = 'OPENSEARCH_ENABLED'
}
if ($Components.Count -eq 0) {
    $Components = @(
        foreach ($entry in $componentFlags.GetEnumerator()) {
            if ($generated[$entry.Value] -eq 'true') {
                $entry.Key
            }
        }
    )
}
$cacheRoot = Join-Path $InstallRoot 'cache'
$configRoot = Join-Path $InstallRoot 'config'
$dataRoot = Join-Path $InstallRoot 'data'
$bindAddress = $generated['OBSERVEWEAVER_BIND_ADDRESS']
$endpointAddress = if ($bindAddress.Contains(':') -and -not $bindAddress.StartsWith('[')) {
    "[$bindAddress]"
}
else {
    $bindAddress
}
$cookieSecure = if ($generated['OBSERVEWEAVER_SCHEME'] -eq 'https') {
    'true'
}
else {
    'false'
}
$winSwVersion = '2.12.0'
$winSwPath = Join-Path $cacheRoot 'WinSW-x64.exe'

if (-not $WhatIfPreference) {
    Assert-Administrator
}

if ($PSCmdlet.ShouldProcess($InstallRoot, 'Create ObserveWeaver directories')) {
    foreach ($path in @($InstallRoot, $cacheRoot, $configRoot, $dataRoot)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
}

Get-Artifact `
    -Uri "https://github.com/winsw/winsw/releases/download/v$winSwVersion/WinSW-x64.exe" `
    -Destination $winSwPath `
    -Checksum '05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA'

if ($Components -contains 'Prometheus') {
    $version = $generated['PROMETHEUS_VERSION']
    $archive = Join-Path $cacheRoot "prometheus-$version.windows-amd64.zip"
    $target = Join-Path $InstallRoot "prometheus-$version"
    Get-Artifact `
        -Uri "https://github.com/prometheus/prometheus/releases/download/v$version/prometheus-$version.windows-amd64.zip" `
        -Destination $archive `
        -Checksum '5409ABDCAC847984AB7869D7814E6E8CFF65B4411D62E7477B960B92EADFA08A'
    Expand-Artifact -Archive $archive -Destination $target
    if (-not $WhatIfPreference) {
        $executable = Get-ChildItem -Path $target -Filter prometheus.exe -Recurse |
            Select-Object -First 1 -ExpandProperty FullName
        $componentConfig = Join-Path $configRoot 'prometheus'
        New-Item -ItemType Directory -Path $componentConfig -Force | Out-Null
        [string[]]$prometheusConfig = @(
            'global:'
            '  scrape_interval: 15s'
            '  evaluation_interval: 15s'
        )
        if ($Components -contains 'Alertmanager') {
            $prometheusConfig += @(
                'alerting:'
                '  alertmanagers:'
                '    - static_configs:'
                "        - targets: [`"127.0.0.1:$($generated['ALERTMANAGER_PORT'])`"]"
            )
        }
        $prometheusConfig += @(
            'scrape_configs:'
            '  - job_name: prometheus'
            '    static_configs:'
            "      - targets: [`"127.0.0.1:$($generated['PROMETHEUS_PORT'])`"]"
        )
        if ($Components -contains 'Alertmanager') {
            $prometheusConfig += @(
                '  - job_name: alertmanager'
                '    static_configs:'
                "      - targets: [`"127.0.0.1:$($generated['ALERTMANAGER_PORT'])`"]"
            )
        }
        if ($Components -contains 'OpenTelemetry') {
            $prometheusConfig += @(
                '  - job_name: otel-collector-internal'
                '    static_configs:'
                "      - targets: [`"127.0.0.1:$($generated['OTEL_METRICS_PORT'])`"]"
                '  - job_name: otel-exported-metrics'
                '    static_configs:'
                "      - targets: [`"127.0.0.1:$($generated['OTEL_PROMETHEUS_PORT'])`"]"
            )
        }
        $prometheusConfig |
            Set-Content `
                -LiteralPath (Join-Path $componentConfig 'prometheus.yml') `
                -Encoding UTF8
        Install-WinSWService `
            -Name 'prometheus' `
            -Executable $executable `
            -Arguments "--config.file=`"$componentConfig\prometheus.yml`" --storage.tsdb.path=`"$dataRoot\prometheus`" --storage.tsdb.retention.time=$($generated['PROMETHEUS_RETENTION']) --web.listen-address=$($endpointAddress):$($generated['PROMETHEUS_PORT'])" `
            -WorkingDirectory (Split-Path -Parent $executable) `
            -WinSWSource $winSwPath
    }
}

if ($Components -contains 'Alertmanager') {
    $version = $generated['ALERTMANAGER_VERSION']
    $archive = Join-Path $cacheRoot "alertmanager-$version.windows-amd64.zip"
    $target = Join-Path $InstallRoot "alertmanager-$version"
    Get-Artifact `
        -Uri "https://github.com/prometheus/alertmanager/releases/download/v$version/alertmanager-$version.windows-amd64.zip" `
        -Destination $archive `
        -Checksum 'B94F1A981ED8E8A07A6E9BE015466E9CD8D180AD8659DFEEED16617248F90B93'
    Expand-Artifact -Archive $archive -Destination $target
    if (-not $WhatIfPreference) {
        $executable = Get-ChildItem -Path $target -Filter alertmanager.exe -Recurse |
            Select-Object -First 1 -ExpandProperty FullName
        $componentConfig = Join-Path $configRoot 'alertmanager'
        New-Item -ItemType Directory -Path $componentConfig -Force | Out-Null
        @"
global:
  resolve_timeout: 5m
route:
  receiver: default
  group_by: [alertname, cluster, service]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
receivers:
  - name: default
"@ | Set-Content -LiteralPath (Join-Path $componentConfig 'alertmanager.yml') -Encoding UTF8
        Install-WinSWService `
            -Name 'alertmanager' `
            -Executable $executable `
            -Arguments "--config.file=`"$componentConfig\alertmanager.yml`" --storage.path=`"$dataRoot\alertmanager`" --web.listen-address=$($endpointAddress):$($generated['ALERTMANAGER_PORT'])" `
            -WorkingDirectory (Split-Path -Parent $executable) `
            -WinSWSource $winSwPath
    }
}

if ($Components -contains 'Grafana') {
    $version = $generated['GRAFANA_VERSION']
    $buildId = '29761037902'
    $installer = Join-Path $cacheRoot "grafana_$($version)_$($buildId)_windows_amd64.msi"
    Get-Artifact `
        -Uri "https://dl.grafana.com/grafana/release/$version/grafana_$($version)_$($buildId)_windows_amd64.msi" `
        -Destination $installer `
        -Checksum 'B27EE67CEA415AC70E0738EAA367837255099014AFCB708972077C342675D2D1'
    if ($PSCmdlet.ShouldProcess($installer, 'Install Grafana Windows service')) {
        $process = Start-Process msiexec.exe `
            -ArgumentList @('/i', "`"$installer`"", '/qn', '/norestart') `
            -Wait `
            -PassThru
        if ($process.ExitCode -notin @(0, 3010)) {
            throw "Grafana MSI failed with exit code $($process.ExitCode)."
        }
        $grafanaHome = Join-Path $env:ProgramFiles 'GrafanaLabs\grafana'
        $customConfig = Join-Path $grafanaHome 'conf\custom.ini'
        @"
[server]
http_addr = $bindAddress
http_port = $($generated['GRAFANA_PORT'])
domain = grafana.$($generated['OBSERVEWEAVER_DOMAIN'])

[security]
admin_user = $($secrets['GRAFANA_ADMIN_USER'])
admin_password = $($secrets['GRAFANA_ADMIN_PASSWORD'])
cookie_secure = $cookieSecure
cookie_samesite = strict

[users]
allow_sign_up = false
"@ | Set-Content -LiteralPath $customConfig -Encoding UTF8
        $datasourceRoot = Join-Path $grafanaHome 'conf\provisioning\datasources'
        New-Item -ItemType Directory -Path $datasourceRoot -Force | Out-Null
        $datasourceFile = Join-Path $datasourceRoot 'observeweaver.yml'
        if ($Components -contains 'Prometheus') {
        @"
apiVersion: 1
datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://127.0.0.1:$($generated['PROMETHEUS_PORT'])
    isDefault: true
    editable: false
"@ | Set-Content -LiteralPath $datasourceFile -Encoding UTF8
        }
        elseif (Test-Path -LiteralPath $datasourceFile) {
            Remove-Item -LiteralPath $datasourceFile -Force
        }
        $grafanaService = Get-Service |
            Where-Object { $_.Name -like 'grafana*' } |
            Select-Object -First 1
        if ($null -ne $grafanaService) {
            Restart-Service -InputObject $grafanaService
        }
    }
}

if ($Components -contains 'OpenTelemetry') {
    $version = $generated['OTELCOL_VERSION']
    $installer = Join-Path $cacheRoot "otelcol-contrib_$($version)_windows_x64.msi"
    Get-Artifact `
        -Uri "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v$version/otelcol-contrib_$($version)_windows_x64.msi" `
        -Destination $installer `
        -Checksum '06E71AE95FDB94DDE25B0F6B3087165DEC7D2DFA0D7A2ECF19921D29E1956922'
    if ($PSCmdlet.ShouldProcess($installer, 'Install OpenTelemetry Collector Windows service')) {
        $process = Start-Process msiexec.exe `
            -ArgumentList @('/i', "`"$installer`"", '/qn', '/norestart') `
            -Wait `
            -PassThru
        if ($process.ExitCode -notin @(0, 3010)) {
            throw "OpenTelemetry Collector MSI failed with exit code $($process.ExitCode)."
        }
        $otelConfigRoot = Join-Path $env:ProgramFiles 'OpenTelemetry Collector Contrib'
        $otelConfig = Join-Path $otelConfigRoot 'config.yaml'
        @"
extensions:
  health_check:
    endpoint: $($endpointAddress):$($generated['OTEL_HEALTH_PORT'])
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: $($endpointAddress):$($generated['OTLP_GRPC_PORT'])
      http:
        endpoint: $($endpointAddress):$($generated['OTLP_HTTP_PORT'])
processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 75
    spike_limit_percentage: 15
  batch: {}
exporters:
  prometheus:
    endpoint: $($endpointAddress):$($generated['OTEL_PROMETHEUS_PORT'])
  debug:
    verbosity: basic
service:
  extensions: [health_check]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: $bindAddress
                port: $($generated['OTEL_METRICS_PORT'])
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [debug]
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [debug]
"@ | Set-Content -LiteralPath $otelConfig -Encoding UTF8
        $otelService = Get-Service |
            Where-Object { $_.Name -like '*otelcol*' -or $_.DisplayName -like '*OpenTelemetry*' } |
            Select-Object -First 1
        if ($null -ne $otelService) {
            Restart-Service -InputObject $otelService
        }
    }
}

if ($Components -contains 'OpenSearch') {
    $version = $generated['OPENSEARCH_VERSION']
    $archive = Join-Path $cacheRoot "opensearch-$version-windows-x64.zip"
    $target = Join-Path $InstallRoot "opensearch-$version"
    Get-Artifact `
        -Uri "https://artifacts.opensearch.org/releases/bundle/opensearch/$version/opensearch-$version-windows-x64.zip" `
        -Destination $archive `
        -Checksum 'E9BA47D5143250269C2083843D15BB4DF363823402C80C1F8650B613AE118E5C7EFD00D60CC38146C26D1C4E8837B2E4B23D3FC90E451833B6FDD255671F7AE8' `
        -Algorithm 'SHA512'
    Expand-Artifact -Archive $archive -Destination $target
    if (-not $WhatIfPreference) {
        $serviceScript = Get-ChildItem -Path $target -Filter opensearch-service.bat -Recurse |
            Select-Object -First 1 -ExpandProperty FullName
        $opensearchHome = Split-Path -Parent (Split-Path -Parent $serviceScript)
        $opensearchConfig = Join-Path $opensearchHome 'config\opensearch.yml'
        @"
cluster.name: observeweaver
node.name: $env:COMPUTERNAME
network.host: $bindAddress
http.port: $($generated['OPENSEARCH_PORT'])
transport.port: $($generated['OPENSEARCH_TRANSPORT_PORT'])
discovery.type: single-node
plugins.security.disabled: true
"@ | Set-Content -LiteralPath $opensearchConfig -Encoding UTF8
        if ($PSCmdlet.ShouldProcess('OpenSearch', 'Install Windows service')) {
            & $serviceScript install
            & $serviceScript start
            $openSearchService = Get-Service |
                Where-Object { $_.Name -like 'opensearch*' } |
                Select-Object -First 1
            if ($null -eq $openSearchService) {
                throw 'OpenSearch Windows service was not created.'
            }
            $openSearchService.WaitForStatus(
                [System.ServiceProcess.ServiceControllerStatus]::Running,
                [TimeSpan]::FromMinutes(2)
            )
            $openSearchReady = $false
            for ($attempt = 0; $attempt -lt 60; $attempt += 1) {
                try {
                    $null = Invoke-RestMethod `
                        -Uri "http://127.0.0.1:$($generated['OPENSEARCH_PORT'])/_cluster/health" `
                        -TimeoutSec 5 `
                        -UseBasicParsing
                    $openSearchReady = $true
                    break
                }
                catch {
                    Start-Sleep -Seconds 2
                }
            }
            if (-not $openSearchReady) {
                throw 'OpenSearch did not become ready within two minutes.'
            }
        }
    }
}

Write-Output 'ObserveWeaver Windows component installation completed.'
Write-Warning 'Graylog Server is not supported natively on Windows. Use a Linux VM, WSL2, or a remote Linux cluster for the full stack.'
