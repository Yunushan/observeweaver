# Security and hardening

## Before production

- Replace example addresses and domains.
- Put Grafana and Graylog behind authenticated TLS ingress.
- Restrict Prometheus, Alertmanager, OpenSearch, MongoDB, and administrative
  APIs to management/workload networks.
- Use a managed internal CA for east-west TLS.
- Replace the bootstrap OpenSearch user database with organization-managed
  identities and authorization.
- Enable TLS and authentication for MongoDB replica-set traffic.
- Encrypt the secret source with SOPS/age or use Vault/External Secrets.
- Configure Grafana OIDC/SAML/LDAP and disable shared local admin use.
- Configure Graylog roles, streams, index retention, and audit controls.
- Define NetworkPolicies and firewall rules from explicit CIDRs.
- Configure OpenSearch snapshots, MongoDB backups, and restore tests.

## Current Compose boundary

The standalone Compose profile keeps MongoDB and OpenSearch on a Docker
`internal` network and publishes neither port. OpenSearch security is disabled
there for deterministic Graylog bootstrap. That is acceptable for a protected
single-host lab or an isolated host backend; it is not zero-trust east-west
security. Do not attach untrusted containers to that network.

The beta multi-host Compose profile also disables OpenSearch security, but it
uses host networking. Its OpenSearch HTTP and transport traffic is plaintext
and unauthenticated. Firewall ports 9200/9300 to the configured data-node
addresses on a trusted, isolated backend network; never expose them to user or
Internet networks.

For authenticated east-west OpenSearch traffic, use the raw Linux deployment
with its generated per-node certificates or Graylog Data Node on K3s/RKE2.

Native Windows OpenSearch also disables the security plugin and is a restricted
lab/agent path, not the full production log backend.

## Native Linux OpenSearch certificates

The raw Linux installer creates a private CA on the first OpenSearch member,
issues a separate HTTP/transport certificate for every member, and includes
each canonical node name and configured IP address in that certificate's SANs.
Graylog trusts this CA through its bundled JVM truststore, and readiness checks
validate the CA rather than bypassing certificate verification.

The CA workspace is `/etc/opensearch/observeweaver-ca` on the first OpenSearch
member. Back it up as protected key material before relying on the cluster.
Node certificates are renewed when fewer than 30 days remain; the ten-year CA
is deliberately not rotated automatically. A CA rotation requires an
operator-controlled maintenance window, truststore replacement, and validation
of every OpenSearch and Graylog member.

## Secret handling

- Never commit `secrets/`, `.env`, private keys, kubeconfigs, or rendered
  credentials.
- Generated secret files use mode 0600 where supported and are not overwritten
  implicitly.
- `docker inspect` can expose environment-based Compose secrets to Docker
  administrators. Docker administrators already have root-equivalent access;
  use Docker secrets or an external provider when that boundary is
  insufficient.
- Helm chart-managed secrets are stored in Kubernetes/Helm release state.
  Encrypt etcd and restrict RBAC.
- Rotate Graylog's administrator password without deleting its password pepper.

## Supply chain

Application and chart versions are exact. Kubernetes chart archives are
verified by SHA-256. CI scans the repository filesystem for configuration,
secret, license, and detectable vulnerability findings; it does not pull and
scan every referenced container image. Production registries should enforce
their own image/SBOM scanning policy. Upgrades require compatibility review
rather than an automated `latest` tag.
