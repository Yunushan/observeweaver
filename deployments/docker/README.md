# Docker deployment

## Standalone

`compose.yml` is the supported one-host deployment. MongoDB and OpenSearch are
on an internal Docker network and are not published. The optional Elastic Stack
adds authenticated Elasticsearch on the configured management port, Kibana on
5601, and Logstash Beats/API listeners on 5045/9600. Run it through
`scripts/observeweaver.sh` so generated values and secrets are loaded
consistently.

Zabbix 7.0.28 LTS runs as a Zabbix Server, Nginx web interface, and dedicated
PostgreSQL service when the `zabbix` profile is enabled. Its web UI is exposed
on port 8080 and its server endpoint on port 10051 by default.

Redis 8.8.0 runs with generated password authentication, AOF persistence, and
an internal-only Docker network endpoint. It is deliberately not published to
the host; use a workload attached to the backend network or `docker compose
exec redis redis-cli` for administrative access.

Kafka runs in combined KRaft mode (ZooKeeper is not used). Apache Kafka 4.3.1
is the default; set `components.kafka.distribution: confluent` with version
`8.3.0` to use the Apache-licensed Confluent Community `cp-kafka` image. The
standalone profile persists broker logs in `kafka-data`, exposes broker port
`9092` on the configured management address, and keeps the controller listener
on the private container network (`9095`). The generated baseline is private
network plaintext; restrict these ports and add TLS/SASL before external
clients connect.

Elasticsearch, Kibana, and Logstash are always rendered at the same 9.4.2
version. The generated secret file supplies the `elastic`, `kibana_system`, and
Logstash writer credentials plus Kibana encryption keys. The one-shot
`elastic-bootstrap` service creates the built-in Kibana password and the
least-privilege `logstash_internal` writer before those workloads start. Put
Kibana behind the same TLS reverse proxy as Grafana and Graylog, and keep
Elasticsearch/Logstash management ports restricted.

## Multi-host cluster (beta)

Docker Compose does not schedule across hosts. ObserveWeaver therefore renders
one explicit bundle per Linux node. Run one Compose project on each configured
node, then initialize MongoDB once:

```bash
CONFIG_FILE=config/examples/docker-cluster.yml scripts/observeweaver.sh validate
CONFIG_FILE=config/examples/docker-cluster.yml scripts/observeweaver.sh render

# Run on obs-01, with the repository and secret file synchronized:
NODE_NAME=obs-01 deployments/docker/deploy-cluster-node.sh

# Repeat on obs-02 and obs-03, then run once on obs-01:
CONFIG_FILE=config/examples/docker-cluster.yml deployments/docker/init-cluster.sh
```

The cluster profile uses host networking so fixed peer addresses work across
hosts. Its OpenSearch security plugin is intentionally disabled because the
image's shared demo certificate cannot authenticate distinct hostnames.
OpenSearch HTTP and transport traffic is therefore plaintext and
unauthenticated. Keep the hosts on a trusted, isolated backend network and
enforce the following firewall rules before deployment:

- MongoDB 27017 and OpenSearch 9200/9300 to data-node addresses only;
- Elasticsearch 9201/9301 to data-node addresses only; Logstash 5045/9600 to
  approved ingestion and management networks;
- Redis 6379 and Sentinel 26379 to data-node/workload addresses only;
- Kafka 9092 and controller 9095 to Kafka data-node addresses and approved
  client networks only;
- Alertmanager 9094 TCP+UDP to metrics-node addresses only;
- administrative HTTP ports to management/ingress networks only;
- GELF/syslog/OTLP to the intended source networks only.

Every data member uses a distinct local volume. External PostgreSQL is required
for Grafana. An external load balancer/VIP is required for user-facing
endpoints. Compose cannot automatically reschedule a failed service to another
host, so this path is beta. Docker standalone uses authenticated Elasticsearch
HTTP. The multi-host Compose Elastic profile keeps Elasticsearch security
disabled until an operator supplies shared transport certificates; its host
network and firewall rules are therefore part of the trust boundary, and its
Logstash pipeline cannot enforce the writer role while security is disabled.
Use raw Linux with its generated per-node
certificates or K3s/RKE2 when authenticated east-west OpenSearch traffic is
required.

Zabbix Server HA is scheduled on the metrics nodes. Before deployment, set
`ZABBIX_DATABASE_HOST`, `ZABBIX_DATABASE_PORT`, `ZABBIX_DATABASE_USER`,
`ZABBIX_DATABASE_PASSWORD`, and `ZABBIX_DATABASE_NAME` in the protected secret
file to a resilient external PostgreSQL service. The database must provide its
own failover; Compose cannot reschedule a failed service to another host.

Redis cluster mode runs one primary, two replicas, and a Sentinel on every
Redis data member. Connect clients through Sentinel (`26379`) and do not pin a
client to the initial `obs-01` primary; Sentinel can promote either replica.
