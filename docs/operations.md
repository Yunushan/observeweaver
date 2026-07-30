# Operations and upgrades

## Backups

Back up each state domain independently:

- OpenSearch/Data Node snapshots to a separate repository.
- MongoDB with replica-set-aware `mongodump` or an operator-supported backup.
- Grafana PostgreSQL plus provisioned dashboards/datasources.
- Zabbix PostgreSQL, including the configuration, history, trends, and event
  data that are all stored in its database. Test a restore against a Zabbix
  Server at the same locked 7.0 LTS patch before relying on it.
- Prometheus snapshots when historical local TSDB recovery is required.
- Graylog content packs, pipeline rules, index-set settings, certificates, and
  the protected secret material.
- Canonical ObserveWeaver config and compatibility locks.

Schedule restore tests. An untested backup is not an availability control.

## Upgrades

1. Review `versions/compatibility.yml`.
2. Read every upstream release and breaking-change note.
3. Back up and test restore.
4. Render the new configuration in CI and a staging environment.
5. Upgrade dependencies in the vendor-required order.
6. Run synthetic metrics/log/alert tests and a node-loss test.
7. Promote the exact tested pins to production.

Graylog upgrades are not rolling: stop all Graylog servers as required by the
upstream upgrade guide, and keep Graylog/Data Node on the same release.
OpenSearch 3.x must never be introduced into the Graylog 7.1 backend.

## Decommissioning and topology changes

Changing `enabled` to `false` or reducing replicas changes newly rendered
placement; it is not an uninstall operation. Stop/disable obsolete stateless
services explicitly. Never remove or reorder MongoDB/OpenSearch members merely
by editing `nodes[]`: reconcile replica membership, shards, snapshots, and
quorum through the upstream tools first. Keep the original first MongoDB member
until an authenticated replica-set reconfiguration and validation is complete.

The first raw OpenSearch member also holds the private CA used to issue node
certificates. Back up `/etc/opensearch/observeweaver-ca` before replacing that
host. Changing a raw node's configured IP reissues its SAN certificate on the
next playbook run, but it does not perform OpenSearch shard or MongoDB
membership changes for you.

## Credential rotation

The raw installer treats `MONGODB_ROOT_PASSWORD` and
`OPENSEARCH_INITIAL_ADMIN_PASSWORD` as bootstrap credentials. Editing the
secret file alone does not change credentials already stored in MongoDB or the
OpenSearch security index. Rotate each credential through its upstream
administration API while the old credential still works, update the external
secret file, rerun the playbook, and verify Graylog before ending the
maintenance window.

## Day-two checks

- Prometheus target/rule health and TSDB growth.
- Alertmanager peer status and notification errors.
- Grafana database/session health.
- OTel Collector refused/dropped telemetry and queue pressure.
- Graylog journal utilization and processing buffers.
- OpenSearch cluster health, unassigned shards, disk watermarks, and snapshots.
- MongoDB replica-set lag, elections, and backup success.
- Zabbix Server queue, database connectivity, and the external PostgreSQL
  backup/failover state.
- Certificate and credential expiration/rotation.

## Production release gates

Before a change is promoted, verify the locked Compose and Kubernetes image
digests against the approved registry/SBOM policy. The Kubernetes installer
post-renders every chart workload image to a lock in
`versions/kubernetes-images.lock.yml` and rejects an image that is not listed.
Treat a changed digest behind an existing tag as a new release that needs the
same compatibility and staging checks.

When updating an image lock, run `scripts/verify_image_locks.py` and
`scripts/verify_kubernetes_image_locks.py` from a registry-authenticated
release environment. These scripts verify that a candidate upstream tag still
resolves to the intended digest; mandatory CI does not perform those live
lookups, because anonymous registry rate limits would make the gate unreliable.

For HA profiles, prove the selected storage, load balancer, external Grafana
PostgreSQL, and external Zabbix PostgreSQL service with an actual node-loss and
restore drill. A rendered configuration or a Helm template is not proof of
those infrastructure guarantees.
