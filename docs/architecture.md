# Architecture

ObserveWeaver separates operator intent from deployment mechanics. The
canonical YAML is validated first, then rendered into non-secret artifacts for
Ansible, Docker Compose, or Helm. A separate gitignored secret file is consumed
only at deployment time.

## Component responsibilities

| Component | Responsibility | Persistent state |
|---|---|---|
| Prometheus | Pull metrics, evaluate rules | Local TSDB per replica |
| Alertmanager | Group, inhibit, route alerts | Small local state; alerts are resent |
| Grafana | Dashboards, queries, UI | SQLite standalone; PostgreSQL/MySQL for HA |
| OTel Collector | Receive/process/export telemetry | Normally stateless |
| Graylog | Log ingestion, processing, search UI | Journal plus MongoDB metadata |
| OpenSearch/Data Node | Graylog search indices | Dedicated volume per member |
| MongoDB | Graylog configuration/metadata | Replica-set volume per member |
| Redis | Optional application cache, queue, and ephemeral state | AOF/RDB volume per member |

## Data paths

- OTLP metrics enter the Collector and are exposed on a Prometheus scrape
  endpoint.
- Prometheus evaluates rules and sends alerts to every Alertmanager replica.
- Grafana queries Prometheus directly.
- GELF, syslog, Beats, and other configured inputs enter Graylog.
- Graylog journals incoming messages and stores searchable indices in
  OpenSearch or Graylog Data Node.
- MongoDB stores Graylog metadata, not the log messages themselves.
- Redis is not coupled to Graylog; applications opt in through their own Redis
  client configuration.
- Traces are not durable until an external trace exporter/backend is configured.

## HA semantics

Replicas do not mean the same thing across the stack:

- Prometheus replicas are independent. A query load balancer may return
  different local data, and duplicates are not merged.
- Alertmanager peers gossip silences and notifications. Prometheus should
  target every peer directly.
- Grafana is active-active only with one shared PostgreSQL/MySQL database.
- OTel gateways are horizontally scalable, but tail sampling and other stateful
  processing require routing affinity.
- Graylog nodes share the same secret pepper, MongoDB replica set, and search
  cluster.
- OpenSearch needs an odd quorum of cluster-manager-eligible nodes and at least
  one index replica to survive one data-node loss.
- MongoDB should use three data-bearing members without an arbiter for
  production.
- Redis uses one password-protected primary in standalone mode. Cluster mode
  uses one primary, two replicas, and three Sentinels; applications must use
  Sentinel discovery rather than a hard-coded primary address.

## Deployment engines

Native Ansible is best when systemd integration and explicit host placement are
required. Docker Compose is the simplest one-host route. K3s/RKE2 plus Helm is
the preferred 3+ node path because it provides scheduling, probes, disruption
control, and declarative upgrades.

ObserveWeaver deliberately does not use Terraform in the core. No cloud,
hypervisor, DNS provider, or VM platform was specified, and application
configuration does not belong in Terraform.
