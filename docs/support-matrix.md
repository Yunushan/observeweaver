# Support matrix

Support means the repository provides a deployment path and the upstream
products support the underlying platform. It does not mean every combination
has identical CI depth.

| Platform | Native | Docker | K3s | RKE2 | Tier |
|---|---:|---:|---:|---:|---|
| Ubuntu 22.04 | Full | Full | Full | Full | 1 |
| Ubuntu 24.04 | Full | Full | Full | Full | 1 |
| Ubuntu 26.04 | Full with external MongoDB | Full | Full | Full | 1/2 |
| Rocky Linux 8 | No | Full | Full | Full | 2 |
| Rocky Linux 9 | Full | Full | Full | Full | 1/2 |
| Rocky Linux 10 | Full with external MongoDB | Full | Full | Full | 1/2 |
| AlmaLinux 8 | No | Full | Full | Full | 2 |
| AlmaLinux 9 | Full | Full | Full | Full | 1/2 |
| AlmaLinux 10 | Full with external MongoDB | Full | Full | Full | 1/2 |
| RHEL 8 | No | Full | Full | Full | 2; licensed runner needed |
| RHEL 9 | Compatible | Full | Full | Full | 2; licensed runner needed |
| RHEL 10 | Compatible with external MongoDB | Full | Full | Full | 2; licensed runner needed |
| Windows 10/11 | Selected components | WSL2 Linux | No server | Client/agent only | 2 |
| Windows Server 2019/2022/2025 | Selected components | Linux VM | No server | Client/agent only | 2/3 |

## Native Windows subset

Prometheus, Alertmanager, Grafana, OTel Collector, and OpenSearch publish
Windows artifacts. Graylog Server does not. MongoDB on Windows does not change
that limitation. The full stack therefore needs Linux.

Windows 10 requires an active Microsoft Extended Security Updates entitlement
or another vendor-supported servicing channel. Windows 11 is preferred for new
desktop deployments.

## Container caveats

Docker Desktop is not a Windows Server production platform. Run Linux
containers in a supported Linux VM on Windows Server. Kubernetes central
workloads use Linux images and Linux nodes.

## Cluster caveats

- K3s does not support Windows server/agent nodes.
- RKE2 server nodes are Linux; Windows agents do not host the central stack.
- The official Graylog 1.0.0 Helm chart is beta and requires Kubernetes 1.32+.
- K3s `local-path` volumes do not make stateful data survive node loss.
- Native binary/package automation currently targets x86_64. Container images
  may support other architectures, but those combinations are not claimed.
- Raw installation on Enterprise Linux 8 is rejected because the maintained
  Ansible Core target runtime and EL8's system DNF Python bindings are
  incompatible. Use EL9 or a Linux-container deployment on EL8.
- MongoDB 8.0's upstream package support currently ends at Ubuntu 24.04 and
  Enterprise Linux 9. For raw Graylog on Ubuntu 26.04 or Enterprise Linux 10,
  set `dependencies.mongodb.external: true` and provide a supported,
  operator-managed `MONGODB_URI`; Docker, K3s, and RKE2 use their own tested
  containerized MongoDB path.

Tiers describe automation depth, not a claim that every OS/runtime combination
is started in CI: tier 1 has maintained configuration, lint, render, and
deployment-definition checks; tier 2 needs environment-specific runtime
confirmation; tier 3 is preview or client-only.

The machine-readable source is
[`support-matrix.yml`](../support-matrix.yml).
