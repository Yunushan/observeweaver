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
