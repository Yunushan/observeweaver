# Configuration reference

Start from one of the files under `config/examples/`. Never edit generated
files under `build/`.

## Top-level sections

| Section | Purpose |
|---|---|
| `metadata` | Deployment name and environment |
| `deployment` | Engine, standalone/cluster mode, namespace |
| `platform` | OS family/distribution and execution layer |
| `nodes` | Names, addresses, and workload roles |
| `network` | DNS base, bind address, VIP, ingress, ports |
| `tls` | Externally provided certificate, cert-manager, or lab-only disabled mode |
| `storage` | StorageClass, persistence semantics, sizes |
| `retention` | Metrics and log retention days |
| `security` | Secret-file reference and plaintext policy |
| `components` | Enable flags, exact versions, replicas, component tuning |
| `dependencies` | MongoDB and PostgreSQL versions plus external-database modes |

## Node roles

- `control`: K3s/RKE2 server/etcd or orchestration role.
- `metrics`: Prometheus, Alertmanager, and Grafana.
- `telemetry`: OTel gateway/agent.
- `logs`: Graylog and Logstash.
- `data`: MongoDB, OpenSearch/Data Node, Elasticsearch, Redis, and Kafka.
- `ingress`: HTTP/TCP/UDP entrypoint, including Kibana.

Compact clusters may assign every role to every node. Split production
deployments should use dedicated workers/data nodes and anti-affinity.

## Port scope

`network.ports` controls the operator-facing listeners and the component ports
that the supported deployment definitions expose. The beta Graylog Helm chart
also creates chart-internal ClusterIP/container listeners on 9833 (metrics) and
13302 (forwarder configuration). ObserveWeaver does not publish those ports,
and the chart currently does not make 13302 configurable.

Redis uses `redis` (default `6379`). In cluster mode it also uses
`redisSentinel` (default `26379`) for the three Sentinel members. Redis is a
private state service, not an ingress workload: do not publish either port to
the Internet. Applications should use the authenticated Redis endpoint in
standalone mode or query the Sentinel service in cluster mode before selecting
the active primary.

Kafka uses `kafka` (default `9092`) for broker/client traffic and
`kafkaController` (default `9095`) for the private KRaft controller quorum. The
generated profile uses Apache Kafka 4.3.1 in combined broker/controller mode by
default. Set `components.kafka.distribution: confluent` and version `8.3.0` to
use the Apache-licensed Confluent Community `cp-kafka` image or raw archive;
both distributions disable ZooKeeper, persist broker logs, and keep listeners
internal to the deployment network. Cluster mode requires an odd quorum of at
least three; restrict both ports to Kafka data nodes and add operator-managed
TLS/SASL before allowing external clients. Commercial Confluent Server features
are not part of this profile.

The optional Elastic Stack uses `elasticsearch`/`elasticsearchTransport` (9201/9301
by default), `kibana` (5601), `logstashBeats` (5045), and `logstashApi` (9600).
Elasticsearch, Kibana, and Logstash must use the same pinned 9.4.2 version. The
generated secret file supplies the `elastic` and `kibana_system` bootstrap
passwords, the `logstash_internal` writer password, and Kibana encryption keys;
Logstash accepts Beats input and writes daily indices to Elasticsearch.
K3s/RKE2 creates a separate internal CA Secret for Elasticsearch HTTPS and
transport TLS; Docker cluster relies on its restricted host network, while raw
Linux uses per-node certificates.

## Storage semantics

`storage.sizes` creates Kubernetes PVC requests. Docker named volumes and raw
host directories consume the capacity of their underlying filesystem; size and
quota enforcement for those engines remains a host/storage-administration
responsibility. `storage.className` and `storage.shared` describe Kubernetes
placement and validation intent and do not resize a native filesystem.

## Secrets

`security.secretFile` is the sole secret-file reference. Generate it with:

```bash
PYTHONPATH=src python3 -m observeweaver.cli secrets \
  --output secrets/observeweaver.env
```

The command refuses to overwrite an existing file unless `--force` is supplied.
For Grafana HA, set the external database host/name/user values in that file.
For raw Graylog on Ubuntu 26.04 or Enterprise Linux 10, set
`dependencies.mongodb.external: true` and replace the generated empty
`MONGODB_URI` with the full URI for a supported, operator-managed MongoDB
deployment. The raw role then skips local MongoDB installation and bootstrap.
In mature environments, replace the env file with SOPS, Vault, or an external
secret controller while preserving the same logical keys.

Elastic deployments additionally require `ELASTICSEARCH_PASSWORD`,
`KIBANA_SYSTEM_PASSWORD`, `KIBANA_ENCRYPTION_KEY`,
`KIBANA_REPORTING_ENCRYPTION_KEY`, `KIBANA_SECURITY_ENCRYPTION_KEY`, and
`LOGSTASH_WRITER_PASSWORD`. The generator creates safe values; rotate them with
the upstream Elastic security tools and update the secret controller together.

`REDIS_PASSWORD` is generated automatically and is required by every Redis
server and Sentinel profile. Redis 8 is source-available under a tri-license;
review the chosen license option and your redistribution/SaaS obligations
before deployment.

## TLS modes

- `provided`: on K3s/RKE2, the installer imports `provided.certificateFile`
  (a PEM/CRT leaf plus any intermediate chain) and `provided.privateKeyFile`
  into `tls.secretName` as a `kubernetes.io/tls` Secret. Grafana, Graylog, Kibana, and
  Zabbix Ingresses reference the same Secret. On raw/Docker, the configured
  external reverse proxy or load balancer owns those file paths and the VIP.
- `cert-manager`: K3s/RKE2 production mode. The installer creates one
  `Certificate` named `tls.secretName` using the named existing `ClusterIssuer`;
  it covers enabled `grafana`, `graylog`, `kibana`, and `zabbix` DNS names plus
  `additionalDnsNames` and `additionalIpAddresses`.
- `disabled`: lab only; validation rejects it in production.

For a wildcard, set `additionalDnsNames` to `*.example.com` and use a
DNS-01-capable issuer. For literal IP addresses, set `additionalIpAddresses`
only when the issuer supports IP SANs; application Ingress routes remain
DNS-host based, so an external proxy/load balancer must route IP clients to the
desired hostname/backend. External termination does not automatically secure
backend traffic. See `docs/security.md` for east-west requirements.

## Validation

Run both examples after changing schema or compatibility rules:

```bash
make validate CONFIG=config/examples/standalone.yml
make validate CONFIG=config/examples/cluster.yml
make test
```

The JSON Schema is useful for editor completion. `owctl validate` remains the
authority for semantic and compatibility rules.
