# Troubleshooting

## Configuration rejected

Run:

```bash
PYTHONPATH=src python3 -m observeweaver.cli validate --config your-config.yml
```

Resolve every `ERROR`. Warnings describe availability limits and do not block
rendering.

## OpenSearch will not start

Check:

- `vm.max_map_count` is at least 262144 on every Linux data node;
- `nofile` is at least 65536;
- heap minimum and maximum are equal and no more than roughly half available
  memory;
- swap is disabled/avoided;
- every data path is writable by the OpenSearch user;
- cluster node names exactly match initial-manager names;
- disk watermarks have not been crossed.

## Graylog cannot connect to search

Confirm Graylog 7.1 uses OpenSearch 2.19.5 or matching Graylog Data Node 7.1.6.
Check CA trust, credentials, the resolved service name, and port 9200. Do not
solve the problem by upgrading to OpenSearch 3.x.

## Elastic Stack services do not become ready

Confirm Elasticsearch is healthy before Kibana or Logstash starts. Check that
all three components use 9.4.2, the Elastic bootstrap and writer credentials are
present, and raw hosts trust `/etc/elasticsearch/observeweaver-root-ca.pem`.
Docker standalone waits for `elastic-bootstrap`; Kubernetes waits for its
bootstrap Job. In cluster mode,
verify the odd data-node quorum and that transport port 9301 is reachable only
between Elasticsearch members. Kibana's encryption keys must be stable across
replicas; changing them invalidates encrypted saved objects.

## Kafka does not become ready

Confirm Java 17 or newer for raw installs (both Apache and Confluent Community), that the KRaft controller port is
reachable between every Kafka data node, and that each node has a unique ID in
the generated quorum voters. A cluster must use an odd number of at least three
brokers with persistent storage; standalone must use replication factor one.
Check `systemctl status kafka`, the `observeweaver-kafka` StatefulSet rollout,
or the Docker health check. Do not reuse a formatted data directory with a
different deployment name/cluster ID without an intentional Kafka migration.

## Graylog cannot connect to MongoDB

Check the replica-set name, `authSource=admin`, credentials, member DNS/IPs, and
majority availability. Verify clock synchronization across nodes.

## Grafana replicas behave inconsistently

Multiple Grafana replicas must use the same PostgreSQL/MySQL database and the
same authentication/session configuration. SQLite files cannot be shared for
active-active HA.

## OTel receives data but nothing is stored

The default metrics pipeline exports a Prometheus scrape endpoint. Logs and
traces use the debug exporter until a Graylog input or external trace backend
is explicitly configured. This prevents silent dependency on an unstable
exporter.
