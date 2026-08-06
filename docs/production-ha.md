# Production high availability

## Compact three-node profile

Each node needs enough CPU, memory, and separate fast storage to run
OpenSearch, Elasticsearch, MongoDB, Graylog, Kibana, Logstash, Prometheus, Alertmanager, Grafana, OTel, and
Kubernetes/system services. OpenSearch is normally the dominant consumer.

A sensible **small** starting point per node is:

- 16 physical/logical CPU cores;
- 64 GB RAM;
- 1–2 TB enterprise NVMe for OpenSearch and journals;
- separate 200–500 GB SSD/NVMe for OS, container images, Prometheus, and
  metadata;
- redundant 10 GbE networking when ingestion or replication is significant.

This is a starting point, not universal sizing. Benchmark with actual active
series, scrape interval, log EPS/bytes, pipeline rules, retention, index
replicas, and query concurrency.

## Split profile

For a stronger production design:

- three RKE2 control-plane/etcd nodes;
- at least three dedicated worker/data nodes;
- OpenSearch/Data Node and Elasticsearch volumes on low-latency block/NVMe storage;
- external HA PostgreSQL for Grafana;
- replicated CSI storage with tested detach/attach failover;
- separate control-plane and ingress VIPs;
- external S3-compatible snapshot storage;
- failure domains across racks/hosts/power;
- one index replica for Graylog data that must survive a node loss.
- an odd Elasticsearch quorum (three or five members) and separate Logstash
  ingestion capacity when Elastic logs are enabled.

## Failure behavior to test

1. Stop one cluster node during ingestion.
2. Confirm MongoDB retains a writable primary.
3. Confirm OpenSearch remains at least yellow and Graylog continues journaling.
4. Confirm Elasticsearch remains at least yellow, Kibana remains reachable, and
   Logstash accepts a test Beats event.
5. Confirm one Prometheus replica still scrapes and alerts.
6. Confirm Alertmanager does not duplicate notifications excessively.
7. Confirm Grafana sessions and dashboards survive a replica loss.
8. Restore the node and confirm shards/replicas converge.
9. Restore from OpenSearch/Elasticsearch snapshots and MongoDB backup into an isolated
   environment.
10. Fail over the external Grafana and Zabbix PostgreSQL services, then confirm
   dashboards and Zabbix Server HA nodes reconnect without data corruption.

Do not call a deployment HA until these tests pass with the chosen storage and
load balancer.

## Load balancing

HTTP/TCP and UDP inputs may need different infrastructure. HAProxy handles
HTTP/TCP but is not a general UDP load balancer. Use a Kubernetes
`LoadBalancer` service, IPVS, NGINX stream with UDP support, or an external
appliance for GELF/syslog UDP. Preserve client IPs when pipelines depend on
them.
