# Native deployment

The Ansible playbook installs systemd-native packages/binaries on Ubuntu and
RHEL-compatible Linux. It uses generated inventory groups to place metrics,
telemetry, log, and data services.

## Controller requirements

- Python 3.11+
- Ansible Core 2.19+
- collections from `ansible/requirements.yml`
- SSH access with sudo on every Linux target
- synchronized DNS/time and explicit firewall rules

Ubuntu 22.04, 24.04, and 26.04 plus Enterprise Linux 9 and 10 (Rocky,
AlmaLinux, or RHEL) are supported for raw installs. Enterprise Linux 8 remains
supported through Docker/K3s/RKE2, but raw installation is rejected because
its system DNF Python bindings are incompatible with maintained Ansible Core.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

ansible-galaxy collection install \
  -r deployments/raw/ansible/requirements.yml

CONFIG_FILE=config/examples/raw-cluster.yml scripts/observeweaver.sh validate
CONFIG_FILE=config/examples/raw-cluster.yml scripts/observeweaver.sh secrets
CONFIG_FILE=config/examples/raw-cluster.yml scripts/observeweaver.sh render
CONFIG_FILE=config/examples/raw-cluster.yml scripts/observeweaver.sh deploy --yes
```

## Required operator inputs

- Replace every documentation IP and domain.
- Set each `nodes[].address`; native services bind to that generated
  `ansible_host`. `network.bindAddress` controls Docker and Windows listeners.
- Configure firewall rules from explicit source CIDRs.
- Supply a load balancer/VIP implementation. ObserveWeaver does not guess
  interface names, VRRP IDs, or corporate routing policy.
- Configure an external HA PostgreSQL endpoint for Grafana replicas.
- Configure an external PostgreSQL endpoint for Zabbix, then set
  `ZABBIX_DATABASE_HOST`, `ZABBIX_DATABASE_PORT`, `ZABBIX_DATABASE_USER`,
  `ZABBIX_DATABASE_PASSWORD`, and `ZABBIX_DATABASE_NAME` in the protected
  secret file. Multiple Zabbix Server nodes use this same database for native
  Zabbix HA; the database itself must provide its own failover.
- Back up `/etc/opensearch/observeweaver-ca` from the first OpenSearch member.
  The installer issues per-node SAN certificates and makes Graylog trust that
  CA; replace it with a managed corporate CA only through a planned rotation.
- Configure UDP load balancing separately from HTTP/TCP.
- Create Graylog GELF/Beats/Syslog inputs in the UI using the reserved ports
  from the canonical config; opening a service port does not create an input.

Native multi-node installation is intentionally serial to avoid simultaneous
quorum changes. Run it in a staging clone before production.

Windows-native subset instructions are under
[`windows/README.md`](windows/README.md).
