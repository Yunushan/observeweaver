# Kubernetes deployment (K3s and RKE2)

ObserveWeaver uses the same Helm deployment on K3s and RKE2. Both server
distributions must run on Linux. Windows may be an administration client, and
RKE2 Windows agents may run telemetry collection workloads, but the central
stateful stack is scheduled to Linux nodes.

## Requirements

- Existing K3s or RKE2 cluster with Kubernetes 1.32 or newer.
- `kubectl`, Helm, `curl`, Python 3, and `sha256sum`.
- A default or explicitly configured persistent `StorageClass`.
- For cluster mode, replicated block storage with tested node-failure
  recovery. K3s `local-path` is suitable only for a lab.
- Existing ingress controller.
- Existing `ClusterIssuer` when `tls.mode` is `cert-manager`.
- At least three schedulable Linux nodes for the HA example.

The installer downloads exact chart archives and verifies their SHA-256
digests. It installs:

- kube-prometheus-stack 87.21.0;
- OpenTelemetry Collector chart 0.165.0, with the configured Contrib image;
- Zabbix chart 7.1.0, configured to use Zabbix 7.0.28 LTS and PostgreSQL;
- Graylog chart 1.0.0 with Graylog/Data Node 7.1.6;
- the Graylog-documented MongoDB Kubernetes operator 1.6.1.

Graylog Data Node manages the OpenSearch backend on Kubernetes. This is the
preferred Graylog architecture and prevents an accidental upgrade to
OpenSearch 3.x. The `components.opensearch` sizing and replica fields configure
the Data Node layer.

`nodes[]` describes and validates the expected cluster topology; Helm does not
rename Kubernetes Nodes or pin workloads to IP addresses. Label/taint actual
nodes through cluster administration when dedicated placement is required.
Likewise, `network.vip` is the address expected from the existing ingress or
load-balancer layer—it is not allocated by the application installer.

Configured Prometheus, Alertmanager, Grafana, Graylog, MongoDB, Data Node, and
OTel ports are rendered into their chart Service values where those charts
support overrides. Graylog input Services reserve GELF/Beats/Syslog ports, but
the corresponding inputs must still be completed in the Graylog UI, as the
official chart notes.

The locked operators fix Alertmanager gossip at `9094` and MongoDB at `27017`;
semantic validation rejects different values for K3s/RKE2. Those two ports
remain editable for raw and Docker deployments.

Zabbix 7.0.28 LTS is deployed with the maintained Zabbix chart. Standalone
profiles use its persistent PostgreSQL backend. The three-node cluster profile
enables native Zabbix Server HA, which requires an operator-managed resilient
PostgreSQL endpoint. Before deployment set `ZABBIX_DATABASE_HOST`,
`ZABBIX_DATABASE_PORT`, `ZABBIX_DATABASE_USER`, `ZABBIX_DATABASE_PASSWORD`, and
`ZABBIX_DATABASE_NAME` in the protected secret file. Its server and web
Services remain ClusterIP so exposure is handled through the operator-managed
ingress or LoadBalancer layer.

OTLP and Graylog input Services are created as `ClusterIP`. Exposing
OTLP/GELF/Beats/Syslog to senders outside the cluster still requires an
operator-managed LoadBalancer, NodePort, or TCP/UDP ingress mapping.

## Deploy

```bash
CONFIG_FILE=config/examples/cluster.yml scripts/observeweaver.sh validate
CONFIG_FILE=config/examples/cluster.yml scripts/observeweaver.sh secrets
CONFIG_FILE=config/examples/cluster.yml scripts/observeweaver.sh render
CONFIG_FILE=config/examples/cluster.yml scripts/observeweaver.sh deploy --yes
```

The official Graylog chart is currently beta. The canonical configuration must
contain `deployment.acceptBetaGraylogChart: true`; validation otherwise stops
the deployment. Render the chart in a non-production cluster and test backup,
restore, failure, and upgrade paths before production use.

## Pod security

The Graylog application can use the restricted Pod Security Standard, but
current Data Node and MongoDB operator workloads require baseline-level
exceptions. ObserveWeaver does not silently relabel an existing namespace.
Review the official chart requirements and your admission policies first.

## Uninstall behavior

Use `helm uninstall` per release when needed. PersistentVolumeClaims are
deliberately not deleted by any supplied script. Data removal is a separate,
explicit operator action.
