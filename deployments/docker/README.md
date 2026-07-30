# Docker deployment

## Standalone

`compose.yml` is the supported one-host deployment. MongoDB and OpenSearch are
on an internal Docker network and are not published. Run it through
`scripts/observeweaver.sh` so generated values and secrets are loaded
consistently.

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
- Alertmanager 9094 TCP+UDP to metrics-node addresses only;
- administrative HTTP ports to management/ingress networks only;
- GELF/syslog/OTLP to the intended source networks only.

Every data member uses a distinct local volume. External PostgreSQL is required
for Grafana. An external load balancer/VIP is required for user-facing
endpoints. Compose cannot automatically reschedule a failed service to another
host, so this path is beta. Use raw Linux with its generated per-node
certificates or K3s/RKE2 when authenticated east-west OpenSearch traffic is
required.
