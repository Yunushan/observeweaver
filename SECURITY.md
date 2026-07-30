# Security policy

## Reporting a vulnerability

Do not open a public issue containing an unpatched vulnerability, credential,
private key, internal address, or exploit details. Use GitHub's private
vulnerability reporting feature for this repository.

Include the affected ObserveWeaver version/commit, deployment engine, impact,
reproduction steps with secrets removed, and a proposed mitigation when known.

## Supported versions

Security fixes are applied to the latest repository release. Upstream product
vulnerabilities follow the exact pins in `versions/stable.yml`; an application
upgrade is released only after compatibility checks, particularly the
Graylog/OpenSearch ceiling.

## Scope

ObserveWeaver cannot guarantee the security of operator-supplied certificates,
networks, plugins, dashboards, images, external databases, or secret providers.
Configuration that weakens a documented control remains the operator's
responsibility.
