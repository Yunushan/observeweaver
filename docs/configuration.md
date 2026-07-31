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
- `logs`: Graylog.
- `data`: MongoDB and OpenSearch/Data Node.
- `ingress`: HTTP/TCP/UDP entrypoint.

Compact clusters may assign every role to every node. Split production
deployments should use dedicated workers/data nodes and anti-affinity.

## Port scope

`network.ports` controls the operator-facing listeners and the component ports
that the supported deployment definitions expose. The beta Graylog Helm chart
also creates chart-internal ClusterIP/container listeners on 9833 (metrics) and
13302 (forwarder configuration). ObserveWeaver does not publish those ports,
and the chart currently does not make 13302 configurable.

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

## TLS modes

- `provided`: raw/Docker production mode. The configured external reverse
  proxy or load balancer owns the certificate/key paths and VIP.
- `cert-manager`: K3s/RKE2 production mode; the named ClusterIssuer must
  already exist.
- `disabled`: lab only; validation rejects it in production.

External termination does not automatically secure backend traffic. See
`docs/security.md` for east-west requirements.

## Validation

Run both examples after changing schema or compatibility rules:

```bash
make validate CONFIG=config/examples/standalone.yml
make validate CONFIG=config/examples/cluster.yml
make test
```

The JSON Schema is useful for editor completion. `owctl validate` remains the
authority for semantic and compatibility rules.
