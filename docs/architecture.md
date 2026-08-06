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
| Elasticsearch | Elastic Stack log indices and queries | Stateful data volume per member |
| Kibana | Elastic Stack search and dashboards UI | Stateless workload; saved objects live in Elasticsearch |
| Logstash | Beats ingestion and pipeline processing | Persistent queue/data volume when enabled |
| MongoDB | Graylog configuration/metadata | Replica-set volume per member |
| Redis | Optional application cache, queue, and ephemeral state | AOF/RDB volume per member |
| Kafka | KRaft event streaming and durable consumer topics | Broker log volume per member |

## Data paths

- OTLP metrics enter the Collector and are exposed on a Prometheus scrape
  endpoint.
- Prometheus evaluates rules and sends alerts to every Alertmanager replica.
- Grafana queries Prometheus directly.
- GELF, syslog, Beats, and other configured inputs enter Graylog.
- Graylog journals incoming messages and stores searchable indices in
  OpenSearch or Graylog Data Node.
- MongoDB stores Graylog metadata, not the log messages themselves.
- Beats or other Logstash inputs are normalized by Logstash and indexed in
  Elasticsearch; Kibana queries those indices. This path is independent of
  Graylog/OpenSearch, so both search backends can be enabled without sharing
  ports or credentials.
- Redis is not coupled to Graylog; applications opt in through their own Redis
  client configuration.
- Kafka is an independent event-streaming plane. Standalone mode runs one
  combined broker/controller; cluster mode runs an odd 3+ KRaft quorum with
  per-member durable logs. Apache Kafka 4.3.1 is the default and Confluent
  Community 8.3.0 is an interchangeable distribution; ZooKeeper is not deployed.
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
- Elasticsearch cluster mode requires an odd quorum of at least three members;
  Kibana and Logstash are deployed only after the Elasticsearch API is ready.
- MongoDB should use three data-bearing members without an arbiter for
  production.
- Redis uses one password-protected primary in standalone mode. Cluster mode
  uses one primary, two replicas, and three Sentinels; applications must use
  Sentinel discovery rather than a hard-coded primary address.
- Kafka cluster mode requires controller and broker listeners on every data
  node, replication factor three, and a replicated persistent volume class for
  durable topic data. The generated baseline listeners are private-network
  plaintext and must be protected by firewall policy or replaced with TLS/SASL.

## Deployment engines

Native Ansible is best when systemd integration and explicit host placement are
required. Docker Compose is the simplest one-host route. K3s/RKE2 plus Helm is
the preferred 3+ node path because it provides scheduling, probes, disruption
control, and declarative upgrades.

ObserveWeaver deliberately does not use Terraform in the core. No cloud,
hypervisor, DNS provider, or VM platform was specified, and application
configuration does not belong in Terraform.
