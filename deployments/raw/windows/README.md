# Windows and Windows Server

Native Windows installation is intentionally limited to software that has an
upstream Windows build:

- Prometheus
- Alertmanager
- Grafana OSS
- OpenTelemetry Collector Contrib
- OpenSearch

Graylog Server has no supported native Windows package. A **full** ObserveWeaver
server on Windows therefore requires one of these execution layers:

- Windows 11: WSL2 plus Docker Desktop in Linux-container mode.
- Windows Server: a Linux VM (Hyper-V is suitable) or a remote Linux
  Docker/K3s/RKE2 cluster.

Windows machines can still send Windows Event Logs and host telemetry to a
central Linux deployment through OpenTelemetry Collector or Graylog Sidecar.

## Native installation

From an elevated PowerShell 5.1 or newer session:

```powershell
python -m pip install -e .
$env:PYTHONPATH = "$PWD\src"
python -m observeweaver.cli validate --config config\examples\windows-native.yml
python -m observeweaver.cli render --config config\examples\windows-native.yml --output build
python -m observeweaver.cli secrets --output secrets\observeweaver.env

.\deployments\raw\windows\Install-ObserveWeaver.ps1 `
  -GeneratedEnvFile .\build\lab\docker\.env.generated `
  -SecretEnvFile .\secrets\observeweaver.env `
  -WhatIf
```

Remove `-WhatIf` after reviewing the proposed actions. The installer is
re-runnable and does not overwrite downloaded component directories unless
`-Force` is supplied.

## Important limits

- The full set of versions and Windows Server editions is render/syntax tested;
  run the native installer in a staging host before each production rollout.
- OpenSearch documents Windows Server 2019 in its tested OS table. Treat newer
  server editions as compatibility targets until validated in your environment.
- Terminate public TLS at IIS, HAProxy, NGINX, or another managed gateway. Do not
  expose native admin ports directly to untrusted networks.
- The lab-oriented native OpenSearch subset disables its security plugin.
  Keep it on a restricted interface; run the full secured central stack on
  Linux for production.
- Version-locked Prometheus, Alertmanager, Grafana, OTel, OpenSearch, and WinSW
  downloads are hash-verified before installation.
- Add Windows Firewall rules only for the management/source CIDRs that need each
  endpoint. The installer does not guess corporate network ranges.
- The repository does not pretend that K3s has Windows server support. RKE2
  Windows agents may collect telemetry, but the central stack remains on Linux.
