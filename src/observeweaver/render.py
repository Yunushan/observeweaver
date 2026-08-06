"""Render deployment-specific, non-secret configuration from the canonical YAML."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
from pathlib import Path
from typing import Any

import yaml

ANY_IPV4 = "0.0.0.0"  # noqa: S104 - rendered for explicitly exposed listeners

# Immutable multi-architecture manifest lists for the application pinset in
# versions/stable.yml. Compose references these values as repository@digest.
DOCKER_IMAGE_TAGS = {
    "prometheus": "prom/prometheus:v3.13.1",
    "alertmanager": "prom/alertmanager:v0.33.1",
    "grafana": "grafana/grafana:13.1.1",
    "opentelemetry": "otel/opentelemetry-collector-contrib:0.157.0",
    "postgresql": "postgres:17",
    "zabbixServer": "zabbix/zabbix-server-pgsql:alpine-7.0.28",
    "zabbixWeb": "zabbix/zabbix-web-nginx-pgsql:alpine-7.0.28",
    "mongodb": "mongo:8.0.28",
    "opensearch": "opensearchproject/opensearch:2.19.5",
    "elasticsearch": "docker.elastic.co/elasticsearch/elasticsearch:9.4.2",
    "kibana": "docker.elastic.co/kibana/kibana:9.4.2",
    "logstash": "docker.elastic.co/logstash/logstash:9.4.2",
    "graylog": "graylog/graylog:7.1.6",
    "redis": "redis:8.8.0",
    "kafka": "apache/kafka:4.3.1",
    "kafkaConfluent": "confluentinc/cp-kafka:8.3.0",
}

DOCKER_IMAGE_LOCKS = {
    "prometheus": (
        "prom/prometheus@sha256:3c42b892cf723fa54d2f262c37a0e1f80aa8c8ddb1da7b9b0df9455a35a7f893"
    ),
    "alertmanager": (
        "prom/alertmanager@sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d"
    ),
    "grafana": (
        "grafana/grafana@sha256:7cb8c64c4d57a57e734073f3cc94620adb24a0acb929bd80ba9f14017e3a975b"
    ),
    "opentelemetry": (
        "otel/opentelemetry-collector-contrib@sha256:"
        "f2f01157055a9b2aab9df7118e1f1c9abf345e99b23bc7a2bc791db374a7d0f6"
    ),
    "postgresql": (
        "postgres@sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317"
    ),
    "zabbixServer": (
        "zabbix/zabbix-server-pgsql@sha256:"
        "7b8628474136fae6e1d643278e46ab6d3cd66146fe0a4dbc64a1d22a61ae0c85"
    ),
    "zabbixWeb": (
        "zabbix/zabbix-web-nginx-pgsql@sha256:"
        "4d109f30358363e4483d4aac43eeec80eb4ec605c9d300f4c235475056c5b06e"
    ),
    "mongodb": ("mongo@sha256:98605bfa1bb2a15dd82109e1d78ad31527a9a744909fab4606076fa71a0ae515"),
    "opensearch": (
        "opensearchproject/opensearch@sha256:"
        "4ee82ecb35d837a6186c81aaa64c8a5bce71aa956edbd87f1f684ab56af52c44"
    ),
    "elasticsearch": (
        "docker.elastic.co/elasticsearch/elasticsearch@sha256:"
        "be5f49784ff5ec8a5b5d7ba17f944d9d6b10c067f596ee93e6b6cb82d2dd874c"
    ),
    "kibana": (
        "docker.elastic.co/kibana/kibana@sha256:"
        "b9749a7672939d1a96dd9c99b86fd84634aab8d03b0889f02177d881aea3eb01"
    ),
    "logstash": (
        "docker.elastic.co/logstash/logstash@sha256:"
        "532fa8633866e231d14b8e8860488f224f7f354bc63b43b099ddf2a3a87e2845"
    ),
    "graylog": (
        "graylog/graylog@sha256:b9a4fd841e4c49c148043265f579554a3bdadf8137ff381b686c194ccb9a3365"
    ),
    "redis": ("redis@sha256:234c902a2db49461a129e2d4aeff85b28cf20187ed274a67f6e50995fa713c7b"),
    "kafka": (
        "apache/kafka@sha256:77e3df9054047a88b520d0cc46e16696d3b22022e1d580aeccd2632df6532837"
    ),
    "kafkaConfluent": (
        "confluentinc/cp-kafka@sha256:"
        "c2cedb691aec9963114fb0b4e45fa49a47bb374a89c241c4ecb68a5fc904e5e3"
    ),
}


def _component(config: dict[str, Any], name: str) -> dict[str, Any]:
    return config["components"][name]


def _replicas(config: dict[str, Any], name: str) -> int:
    value = _component(config, name).get("replicas", 1)
    return max(1, int(value))


def _endpoint_host(host: str) -> str:
    """Bracket IPv6 literals when they are embedded in host:port endpoints."""
    try:
        return f"[{host}]" if ipaddress.ip_address(host).version == 6 else host
    except ValueError:
        return host


def _host_port(host: str, port: int) -> str:
    return f"{_endpoint_host(host)}:{port}"


def _kafka_cluster_id(config: dict[str, Any]) -> str:
    """Return a stable Kafka KRaft cluster id for this deployment name."""
    digest = hashlib.sha256(
        f"observeweaver:{config['metadata']['name']}".encode()
    ).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _kafka_distribution(config: dict[str, Any]) -> str:
    """Return the selected Kafka distribution, preserving Apache compatibility."""
    return str(_component(config, "kafka").get("distribution", "apache"))


def _kafka_image_lock(config: dict[str, Any]) -> str:
    key = "kafkaConfluent" if _kafka_distribution(config) == "confluent" else "kafka"
    return DOCKER_IMAGE_LOCKS[key]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _docker_env(config: dict[str, Any]) -> str:
    ports = config["network"]["ports"]
    storage = config["storage"]
    bind_address = config["network"].get("bindAddress", ANY_IPV4)
    active_profiles = [
        name
        for name in (
            "prometheus",
            "alertmanager",
            "grafana",
            "opentelemetry",
            "zabbix",
            "graylog",
            "opensearch",
            "elasticsearch",
            "kibana",
            "logstash",
            "redis",
            "kafka",
        )
        if _component(config, name)["enabled"]
    ]
    if _component(config, "graylog")["enabled"]:
        active_profiles.append("mongodb")
    entries = {
        "OBSERVEWEAVER_DOMAIN": config["network"]["domain"],
        "OBSERVEWEAVER_SCHEME": "https" if config["tls"]["mode"] != "disabled" else "http",
        "OBSERVEWEAVER_BIND_ADDRESS": bind_address,
        "OBSERVEWEAVER_ENDPOINT_ADDRESS": _endpoint_host(bind_address),
        "OBSERVEWEAVER_MODE": config["deployment"]["mode"],
        "PROMETHEUS_VERSION": _component(config, "prometheus")["version"],
        "PROMETHEUS_ENABLED": str(_component(config, "prometheus")["enabled"]).lower(),
        "ALERTMANAGER_VERSION": _component(config, "alertmanager")["version"],
        "ALERTMANAGER_ENABLED": str(_component(config, "alertmanager")["enabled"]).lower(),
        "GRAFANA_VERSION": _component(config, "grafana")["version"],
        "GRAFANA_ENABLED": str(_component(config, "grafana")["enabled"]).lower(),
        "OTELCOL_VERSION": _component(config, "opentelemetry")["version"],
        "OTELCOL_ENABLED": str(_component(config, "opentelemetry")["enabled"]).lower(),
        "ZABBIX_VERSION": _component(config, "zabbix")["version"],
        "ZABBIX_ENABLED": str(_component(config, "zabbix")["enabled"]).lower(),
        "GRAYLOG_VERSION": _component(config, "graylog")["version"],
        "GRAYLOG_ENABLED": str(_component(config, "graylog")["enabled"]).lower(),
        "OPENSEARCH_VERSION": _component(config, "opensearch")["version"],
        "OPENSEARCH_ENABLED": str(_component(config, "opensearch")["enabled"]).lower(),
        "ELASTICSEARCH_VERSION": _component(config, "elasticsearch")["version"],
        "ELASTICSEARCH_ENABLED": str(_component(config, "elasticsearch")["enabled"]).lower(),
        "ELASTICSEARCH_SECURITY_ENABLED": "false",
        "KIBANA_VERSION": _component(config, "kibana")["version"],
        "KIBANA_ENABLED": str(_component(config, "kibana")["enabled"]).lower(),
        "LOGSTASH_VERSION": _component(config, "logstash")["version"],
        "LOGSTASH_ENABLED": str(_component(config, "logstash")["enabled"]).lower(),
        "REDIS_VERSION": _component(config, "redis")["version"],
        "REDIS_ENABLED": str(_component(config, "redis")["enabled"]).lower(),
        "KAFKA_DISTRIBUTION": _kafka_distribution(config),
        "KAFKA_VERSION": _component(config, "kafka")["version"],
        "KAFKA_ENABLED": str(_component(config, "kafka")["enabled"]).lower(),
        "KAFKA_IMAGE": _kafka_image_lock(config),
        "KAFKA_CLUSTER_ID": _kafka_cluster_id(config),
        "MONGODB_VERSION": config["dependencies"]["mongodb"]["version"],
        "POSTGRES_VERSION": config["dependencies"]["postgresql"]["version"],
        "PROMETHEUS_IMAGE": DOCKER_IMAGE_LOCKS["prometheus"],
        "ALERTMANAGER_IMAGE": DOCKER_IMAGE_LOCKS["alertmanager"],
        "GRAFANA_IMAGE": DOCKER_IMAGE_LOCKS["grafana"],
        "OTELCOL_IMAGE": DOCKER_IMAGE_LOCKS["opentelemetry"],
        "POSTGRES_IMAGE": DOCKER_IMAGE_LOCKS["postgresql"],
        "ZABBIX_SERVER_IMAGE": DOCKER_IMAGE_LOCKS["zabbixServer"],
        "ZABBIX_WEB_IMAGE": DOCKER_IMAGE_LOCKS["zabbixWeb"],
        "MONGODB_IMAGE": DOCKER_IMAGE_LOCKS["mongodb"],
        "OPENSEARCH_IMAGE": DOCKER_IMAGE_LOCKS["opensearch"],
        "ELASTICSEARCH_IMAGE": DOCKER_IMAGE_LOCKS["elasticsearch"],
        "KIBANA_IMAGE": DOCKER_IMAGE_LOCKS["kibana"],
        "LOGSTASH_IMAGE": DOCKER_IMAGE_LOCKS["logstash"],
        "GRAYLOG_IMAGE": DOCKER_IMAGE_LOCKS["graylog"],
        "REDIS_IMAGE": DOCKER_IMAGE_LOCKS["redis"],
        "PROMETHEUS_PORT": ports["prometheus"],
        "ALERTMANAGER_PORT": ports["alertmanager"],
        "ALERTMANAGER_CLUSTER_PORT": ports["alertmanagerCluster"],
        "GRAFANA_PORT": ports["grafana"],
        "OTLP_GRPC_PORT": ports["otlpGrpc"],
        "OTLP_HTTP_PORT": ports["otlpHttp"],
        "OTEL_HEALTH_PORT": ports["otelHealth"],
        "OTEL_METRICS_PORT": ports["otelMetrics"],
        "OTEL_PROMETHEUS_PORT": ports["otelPrometheus"],
        "ZABBIX_SERVER_PORT": ports["zabbixServer"],
        "ZABBIX_WEB_PORT": ports["zabbixWeb"],
        "GRAYLOG_HTTP_PORT": ports["graylogHttp"],
        "GRAYLOG_DATANODE_PORT": ports["graylogDataNode"],
        "GRAYLOG_BEATS_PORT": ports["graylogBeats"],
        "GRAYLOG_GELF_TCP_PORT": ports["graylogGelfTcp"],
        "GRAYLOG_GELF_UDP_PORT": ports["graylogGelfUdp"],
        "GRAYLOG_SYSLOG_TCP_PORT": ports["graylogSyslogTcp"],
        "GRAYLOG_SYSLOG_UDP_PORT": ports["graylogSyslogUdp"],
        "OPENSEARCH_PORT": ports["opensearch"],
        "OPENSEARCH_TRANSPORT_PORT": ports["opensearchTransport"],
        "ELASTICSEARCH_PORT": ports["elasticsearch"],
        "ELASTICSEARCH_TRANSPORT_PORT": ports["elasticsearchTransport"],
        "KIBANA_PORT": ports["kibana"],
        "LOGSTASH_BEATS_PORT": ports["logstashBeats"],
        "LOGSTASH_API_PORT": ports["logstashApi"],
        "MONGODB_PORT": ports["mongodb"],
        "REDIS_PORT": ports["redis"],
        "REDIS_SENTINEL_PORT": ports["redisSentinel"],
        "KAFKA_PORT": ports["kafka"],
        "KAFKA_CONTROLLER_PORT": ports["kafkaController"],
        "PROMETHEUS_RETENTION": f"{config['retention']['metricsDays']}d",
        "GRAYLOG_RETENTION_DAYS": config["retention"]["logsDays"],
        "GRAYLOG_ELASTICSEARCH_REPLICAS": (1 if config["deployment"]["mode"] == "cluster" else 0),
        "OPENSEARCH_JAVA_OPTS": _component(config, "opensearch").get("javaOpts", "-Xms2g -Xmx2g"),
        "STORAGE_CLASS": storage.get("className", ""),
        "SECRETS_FILE": config["security"]["secretFile"],
        "COMPOSE_PROFILES": ",".join(active_profiles),
    }
    lines = [
        "# Generated by owctl. Do not put secrets in this file.",
        "# Load the separate SECRETS_FILE before starting the deployment.",
    ]
    lines.extend(f"{key}={value}" for key, value in entries.items())
    return "\n".join(lines) + "\n"


def _docker_standalone_configs(config: dict[str, Any]) -> dict[str, str]:
    ports = config["network"]["ports"]
    scrape_configs = []
    scrape_targets = (
        ("prometheus", "prometheus", ports["prometheus"]),
        ("alertmanager", "alertmanager", ports["alertmanager"]),
        ("grafana", "grafana", ports["grafana"]),
    )
    for component_name, host, port in scrape_targets:
        if _component(config, component_name)["enabled"]:
            scrape_configs.append(
                {
                    "job_name": component_name,
                    "static_configs": [{"targets": [f"{host}:{port}"]}],
                }
            )
    if _component(config, "opentelemetry")["enabled"]:
        scrape_configs.extend(
            [
                {
                    "job_name": "otel-collector-internal",
                    "static_configs": [{"targets": [f"otel-collector:{ports['otelMetrics']}"]}],
                },
                {
                    "job_name": "otel-exported-metrics",
                    "static_configs": [{"targets": [f"otel-collector:{ports['otelPrometheus']}"]}],
                },
            ]
        )
    prometheus = {
        "global": {"scrape_interval": "15s", "evaluation_interval": "15s"},
        "rule_files": ["/etc/prometheus/rules.yml"],
        "scrape_configs": scrape_configs,
    }
    if _component(config, "alertmanager")["enabled"]:
        prometheus["alerting"] = {
            "alertmanagers": [
                {"static_configs": [{"targets": [f"alertmanager:{ports['alertmanager']}"]}]}
            ]
        }
    alertmanager = {
        "global": {"resolve_timeout": "5m"},
        "route": {
            "receiver": "default",
            "group_by": ["alertname", "cluster", "service"],
            "group_wait": "30s",
            "group_interval": "5m",
            "repeat_interval": "4h",
        },
        "receivers": [{"name": "default"}],
    }
    otel = {
        "extensions": {"health_check": {"endpoint": f"0.0.0.0:{ports['otelHealth']}"}},
        "receivers": {
            "otlp": {
                "protocols": {
                    "grpc": {"endpoint": f"0.0.0.0:{ports['otlpGrpc']}"},
                    "http": {"endpoint": f"0.0.0.0:{ports['otlpHttp']}"},
                }
            }
        },
        "processors": {
            "memory_limiter": {
                "check_interval": "1s",
                "limit_percentage": 75,
                "spike_limit_percentage": 15,
            },
            "batch": {"send_batch_size": 8192, "timeout": "5s"},
        },
        "exporters": {
            "prometheus": {
                "endpoint": f"0.0.0.0:{ports['otelPrometheus']}",
                "namespace": "otel",
            },
            "debug": {"verbosity": "basic"},
        },
        "service": {
            "extensions": ["health_check"],
            "telemetry": {
                "metrics": {
                    "readers": [
                        {
                            "pull": {
                                "exporter": {
                                    "prometheus": {
                                        "host": ANY_IPV4,
                                        "port": ports["otelMetrics"],
                                    }
                                }
                            }
                        }
                    ]
                }
            },
            "pipelines": {
                signal: {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "batch"],
                    "exporters": ["prometheus"] if signal == "metrics" else ["debug"],
                }
                for signal in ("metrics", "logs", "traces")
            },
        },
    }
    prometheus_datasources = (
        [
            {
                "name": "Prometheus",
                "uid": "prometheus",
                "type": "prometheus",
                "access": "proxy",
                "url": f"http://prometheus:{ports['prometheus']}",
                "isDefault": True,
                "editable": False,
                "jsonData": {
                    "httpMethod": "POST",
                    "prometheusType": "Prometheus",
                    "timeInterval": "15s",
                },
            }
        ]
        if _component(config, "prometheus")["enabled"]
        else []
    )
    datasource = {
        "apiVersion": 1,
        "deleteDatasources": [{"name": "Prometheus", "orgId": 1}],
        "datasources": prometheus_datasources,
    }
    rules = {
        "groups": [
            {
                "name": "observeweaver",
                "rules": [
                    {
                        "alert": "ObserveWeaverTargetDown",
                        "expr": "up == 0",
                        "for": "5m",
                        "labels": {"severity": "warning"},
                        "annotations": {
                            "summary": "ObserveWeaver target is down",
                            "description": (
                                "{{ $labels.job }} / {{ $labels.instance }} "
                                "has been unreachable for 5 minutes."
                            ),
                        },
                    }
                ],
            }
        ]
    }
    logstash = f"""input {{
  beats {{
    port => {ports['logstashBeats']}
    host => \"0.0.0.0\"
  }}
}}

filter {{
  mutate {{ add_field => {{ \"[observeweaver][managed]\" => \"true\" }} }}
}}

output {{
  elasticsearch {{
    hosts => [\"http://elasticsearch:{ports['elasticsearch']}\"]
    user => \"logstash_internal\"
    password => \"${{LOGSTASH_WRITER_PASSWORD}}\"
    index => \"observeweaver-logs-%{{+YYYY.MM.dd}}\"
  }}
}}
"""
    return {
        "prometheus.yml": yaml.safe_dump(prometheus, sort_keys=False),
        "prometheus-rules.yml": yaml.safe_dump(rules, sort_keys=False),
        "alertmanager.yml": yaml.safe_dump(alertmanager, sort_keys=False),
        "otel-collector.yml": yaml.safe_dump(otel, sort_keys=False),
        "grafana-datasources.yml": yaml.safe_dump(datasource, sort_keys=False),
        "logstash.conf": logstash,
    }


def _inventory(config: dict[str, Any]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {
        "observeweaver": config["nodes"],
        "control": [],
        "metrics": [],
        "telemetry": [],
        "logs": [],
        "data": [],
        "ingress": [],
    }
    for node in config["nodes"]:
        for role in node["roles"]:
            groups.setdefault(role, []).append(node)
    component_roles = {
        "prometheus": "metrics",
        "alertmanager": "metrics",
        "grafana": "metrics",
        "opentelemetry": "telemetry",
        "graylog": "logs",
        "opensearch": "data",
        "elasticsearch": "data",
        "kibana": "ingress",
        "logstash": "logs",
        "redis": "data",
        "kafka": "data",
    }
    for component_name, role in component_roles.items():
        eligible = groups.get(role, [])
        groups[component_name] = (
            eligible[: _replicas(config, component_name)]
            if _component(config, component_name)["enabled"]
            else []
        )
    mongodb_replicas = 3 if config["deployment"]["mode"] == "cluster" else 1
    groups["mongodb"] = (
        groups.get("data", [])[:mongodb_replicas]
        if _component(config, "graylog")["enabled"]
        else []
    )
    lines = ["# Generated by owctl."]
    for group, nodes in groups.items():
        lines.append(f"\n[{group}]")
        for node in nodes:
            lines.append(f"{node['name']} ansible_host={node['address']}")
    lines.extend(
        [
            "\n[observeweaver:vars]",
            f"observeweaver_mode={config['deployment']['mode']}",
            f"observeweaver_domain={config['network']['domain']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _group_vars(config: dict[str, Any]) -> str:
    safe_config = {
        "observeweaver": {
            "metadata": config["metadata"],
            "deployment": config["deployment"],
            "platform": config["platform"],
            "network": config["network"],
            "tls": config["tls"],
            "storage": config["storage"],
            "retention": config["retention"],
            "components": config["components"],
            "dependencies": config["dependencies"],
            "kafka_cluster_id": _kafka_cluster_id(config),
            "secret_file": config["security"]["secretFile"],
        }
    }
    return "# Generated by owctl; contains no secret values.\n" + yaml.safe_dump(
        safe_config, sort_keys=False
    )


def _public_tls_dns_names(config: dict[str, Any]) -> list[str]:
    """Return deterministic DNS SANs for public web endpoints and user additions."""
    domain = config["network"]["domain"]
    names = [
        f"{component}.{domain}"
        for component in ("grafana", "graylog", "zabbix", "kibana")
        if _component(config, component)["enabled"]
    ]
    names.extend(config["tls"].get("additionalDnsNames", []))
    return list(dict.fromkeys(names))


def _public_tls_manifest(config: dict[str, Any]) -> dict[str, Any]:
    """Render a cert-manager Certificate without embedding certificate material."""
    if config["tls"]["mode"] != "cert-manager":
        return {"apiVersion": "v1", "kind": "List", "items": []}

    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "cert-manager.io/v1",
                "kind": "Certificate",
                "metadata": {"name": config["tls"]["secretName"]},
                "spec": {
                    "secretName": config["tls"]["secretName"],
                    "issuerRef": {
                        "name": config["tls"]["certManager"]["clusterIssuer"],
                        "kind": "ClusterIssuer",
                        "group": "cert-manager.io",
                    },
                    "dnsNames": _public_tls_dns_names(config),
                    "ipAddresses": config["tls"].get("additionalIpAddresses", []),
                },
            }
        ],
    }


def _redis_kubernetes_manifest(config: dict[str, Any]) -> dict[str, Any]:
    """Render a password-protected Redis StatefulSet and Sentinel HA topology."""
    if not _component(config, "redis")["enabled"]:
        return {"apiVersion": "v1", "kind": "List", "items": []}

    ports = config["network"]["ports"]
    storage = config["storage"]
    secret_name = config["security"]["kubernetesSecretName"]
    cluster_mode = config["deployment"]["mode"] == "cluster"
    replicas = _replicas(config, "redis")
    labels = {"app.kubernetes.io/name": "observeweaver-redis"}
    redis_command = (
        """\
set -eu
if [ \"${HOSTNAME##*-}\" = \"0\" ]; then
  exec redis-server --bind 0.0.0.0 --port \"${REDIS_PORT}\" --appendonly yes \\
    --appendfsync everysec --protected-mode yes --requirepass \"${REDIS_PASSWORD}\"
fi
exec redis-server --bind 0.0.0.0 --port \"${REDIS_PORT}\" --appendonly yes \\
  --appendfsync everysec --protected-mode yes --requirepass \"${REDIS_PASSWORD}\" \\
  --masterauth \"${REDIS_PASSWORD}\" --replicaof \\
  observeweaver-redis-0.observeweaver-redis \"${REDIS_PORT}\"
"""
        if cluster_mode
        else """\
exec redis-server --bind 0.0.0.0 --port \"${REDIS_PORT}\" --appendonly yes \\
  --appendfsync everysec --protected-mode yes --requirepass \"${REDIS_PASSWORD}\"
"""
    )
    redis_container: dict[str, Any] = {
        "name": "redis",
        "image": DOCKER_IMAGE_LOCKS["redis"],
        "imagePullPolicy": "IfNotPresent",
        "command": ["/bin/sh", "-ec", redis_command],
        "env": [
            {"name": "REDIS_PORT", "value": str(ports["redis"])},
            {
                "name": "REDIS_PASSWORD",
                "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "REDIS_PASSWORD"}},
            },
        ],
        "ports": [{"name": "redis", "containerPort": ports["redis"]}],
        "volumeMounts": [{"name": "data", "mountPath": "/data"}],
        "livenessProbe": {
            "exec": {
                "command": [
                    "/bin/sh",
                    "-ec",
                    'test "$(redis-cli --no-auth-warning -a "$REDIS_PASSWORD" ping)" = PONG',
                ]
            },
            "initialDelaySeconds": 20,
            "periodSeconds": 10,
        },
        "readinessProbe": {
            "exec": {
                "command": [
                    "/bin/sh",
                    "-ec",
                    'test "$(redis-cli --no-auth-warning -a "$REDIS_PASSWORD" ping)" = PONG',
                ]
            },
            "initialDelaySeconds": 5,
            "periodSeconds": 5,
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": False,
            "capabilities": {"drop": ["ALL"]},
        },
    }
    containers = [redis_container]
    if cluster_mode:
        sentinel_command = """\
set -eu
cat >/tmp/sentinel.conf <<EOF
port ${REDIS_SENTINEL_PORT}
bind 0.0.0.0
protected-mode yes
sentinel monitor observeweaver observeweaver-redis-0.observeweaver-redis ${REDIS_PORT} 2
sentinel auth-pass observeweaver ${REDIS_PASSWORD}
sentinel down-after-milliseconds observeweaver 5000
sentinel failover-timeout observeweaver 60000
sentinel parallel-syncs observeweaver 1
EOF
exec redis-server /tmp/sentinel.conf --sentinel
"""
        containers.append(
            {
                "name": "sentinel",
                "image": DOCKER_IMAGE_LOCKS["redis"],
                "imagePullPolicy": "IfNotPresent",
                "command": ["/bin/sh", "-ec", sentinel_command],
                "env": [
                    {"name": "REDIS_PORT", "value": str(ports["redis"])},
                    {"name": "REDIS_SENTINEL_PORT", "value": str(ports["redisSentinel"])},
                    {
                        "name": "REDIS_PASSWORD",
                        "valueFrom": {
                            "secretKeyRef": {"name": secret_name, "key": "REDIS_PASSWORD"}
                        },
                    },
                ],
                "ports": [{"name": "sentinel", "containerPort": ports["redisSentinel"]}],
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": False,
                    "capabilities": {"drop": ["ALL"]},
                },
            }
        )
    stateful_set = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": "observeweaver-redis", "labels": labels},
        "spec": {
            "serviceName": "observeweaver-redis",
            "replicas": replicas,
            "podManagementPolicy": "OrderedReady",
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "securityContext": {"fsGroup": 999, "runAsNonRoot": True},
                    "containers": containers,
                },
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "data"},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "storageClassName": storage.get("className"),
                        "resources": {"requests": {"storage": storage["sizes"]["redis"]}},
                    },
                }
            ],
        },
    }
    network_policy_ports = [{"protocol": "TCP", "port": ports["redis"]}]
    if cluster_mode:
        network_policy_ports.append({"protocol": "TCP", "port": ports["redisSentinel"]})
    items: list[dict[str, Any]] = [
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "observeweaver-redis", "labels": labels},
            "spec": {
                "clusterIP": "None",
                "selector": labels,
                "ports": [{"name": "redis", "port": ports["redis"], "targetPort": "redis"}],
            },
        },
        stateful_set,
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "observeweaver-redis-private"},
            "spec": {
                "podSelector": {"matchLabels": labels},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [{"podSelector": {}}],
                        "ports": network_policy_ports,
                    }
                ],
            },
        },
    ]
    if cluster_mode:
        items.insert(
            1,
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "observeweaver-redis-sentinel", "labels": labels},
                "spec": {
                    "selector": labels,
                    "ports": [
                        {
                            "name": "sentinel",
                            "port": ports["redisSentinel"],
                            "targetPort": "sentinel",
                        }
                    ],
                },
            },
        )
    return {"apiVersion": "v1", "kind": "List", "items": items}


def _elastic_kubernetes_manifest(config: dict[str, Any]) -> dict[str, Any]:
    """Render locked-image Elasticsearch, Kibana, and Logstash resources.

    The resources deliberately use the upstream container images directly rather
    than an unpinned third-party chart. Elasticsearch owns durable quorum data,
    Kibana remains stateless, and Logstash gets a per-replica durable data volume. Credentials
    are always read from the generated Kubernetes secret.
    """
    if not _component(config, "elasticsearch")["enabled"]:
        return {"apiVersion": "v1", "kind": "List", "items": []}

    ports = config["network"]["ports"]
    storage = config["storage"]
    sizes = storage["sizes"]
    namespace = config["deployment"]["namespace"]
    secret_name = config["security"].get("kubernetesSecretName", "observeweaver-secrets")
    domain = config["network"]["domain"]
    ingress_enabled = config["network"]["ingress"]["enabled"]
    ingress_class = config["network"]["ingress"].get("className", "")
    tls_enabled = ingress_enabled and config["tls"]["mode"] != "disabled"
    tls_secret_name = config["tls"]["secretName"]
    cluster_mode = config["deployment"]["mode"] == "cluster"
    es_name = "observeweaver-elasticsearch"
    es_headless = f"{es_name}-headless"
    elastic_tls_secret_name = f"{es_name}-transport-tls"
    es_replicas = _replicas(config, "elasticsearch")
    es_hosts = (
        f"{es_headless}.{namespace}.svc.cluster.local:"
        f"{ports['elasticsearchTransport']}"
    )
    es_config_lines = [
        "cluster.name: observeweaver-elastic",
        "node.name: ${HOSTNAME}",
        "network.host: 0.0.0.0",
        f"http.port: {ports['elasticsearch']}",
        f"transport.port: {ports['elasticsearchTransport']}",
        "xpack.security.enabled: true",
        "xpack.security.http.ssl.enabled: true",
        "xpack.security.http.ssl.certificate: /usr/share/elasticsearch/config/certs/tls.crt",
        "xpack.security.http.ssl.key: /usr/share/elasticsearch/config/certs/tls.key",
        "xpack.security.http.ssl.certificate_authorities: "
        "[/usr/share/elasticsearch/config/certs/ca.crt]",
        "xpack.security.transport.ssl.enabled: true",
        "xpack.security.transport.ssl.verification_mode: certificate",
        "xpack.security.transport.ssl.certificate: /usr/share/elasticsearch/config/certs/tls.crt",
        "xpack.security.transport.ssl.key: /usr/share/elasticsearch/config/certs/tls.key",
        "xpack.security.transport.ssl.certificate_authorities: "
        "[/usr/share/elasticsearch/config/certs/ca.crt]",
        "bootstrap.memory_lock: true",
    ]
    if cluster_mode:
        es_config_lines.extend(
            [
                f"discovery.seed_hosts: [{es_hosts}]",
                "cluster.initial_master_nodes: ["
                + ", ".join(f"{es_name}-{index}" for index in range(es_replicas))
                + "]",
                "node.roles: [master, data, ingest, remote_cluster_client]",
            ]
        )
    else:
        es_config_lines.append("discovery.type: single-node")

    items: list[dict[str, Any]] = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": f"{es_name}-config", "namespace": namespace},
            "data": {"elasticsearch.yml": "\n".join(es_config_lines) + "\n"},
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": es_headless, "namespace": namespace},
            "spec": {
                "clusterIP": "None",
                "publishNotReadyAddresses": True,
                "selector": {"app.kubernetes.io/name": es_name},
                "ports": [
                    {"name": "http", "port": ports["elasticsearch"], "targetPort": "http"},
                    {
                        "name": "transport",
                        "port": ports["elasticsearchTransport"],
                        "targetPort": "transport",
                    },
                ],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": es_name, "namespace": namespace},
            "spec": {
                "selector": {"app.kubernetes.io/name": es_name},
                "ports": [
                    {"name": "http", "port": ports["elasticsearch"], "targetPort": "http"}
                ],
            },
        },
        {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": es_name, "namespace": namespace},
            "spec": {
                "serviceName": es_headless,
                "replicas": es_replicas,
                "podManagementPolicy": "Parallel",
                "selector": {"matchLabels": {"app.kubernetes.io/name": es_name}},
                "template": {
                    "metadata": {"labels": {"app.kubernetes.io/name": es_name}},
                    "spec": {
                        "terminationGracePeriodSeconds": 120,
                        "securityContext": {"fsGroup": 1000},
                        "containers": [
                            {
                                "name": "elasticsearch",
                                "image": DOCKER_IMAGE_LOCKS["elasticsearch"],
                                "imagePullPolicy": "IfNotPresent",
                                "ports": [
                                    {"name": "http", "containerPort": ports["elasticsearch"]},
                                    {
                                        "name": "transport",
                                        "containerPort": ports["elasticsearchTransport"],
                                    },
                                ],
                                "env": [
                                    {
                                        "name": "ELASTIC_PASSWORD",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": secret_name,
                                                "key": "ELASTICSEARCH_PASSWORD",
                                            }
                                        },
                                    },
                                    {"name": "ES_JAVA_OPTS", "value": "-Xms2g -Xmx2g"},
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "config",
                                        "mountPath": (
                                            "/usr/share/elasticsearch/config/"
                                            "elasticsearch.yml"
                                        ),
                                        "subPath": "elasticsearch.yml",
                                    },
                                    {"name": "data", "mountPath": "/usr/share/elasticsearch/data"},
                                    {
                                        "name": "certs",
                                        "mountPath": "/usr/share/elasticsearch/config/certs",
                                        "readOnly": True,
                                    },
                                ],
                                "readinessProbe": {
                                    "tcpSocket": {"port": "http"},
                                    "periodSeconds": 10,
                                    "failureThreshold": 12,
                                },
                                "startupProbe": {
                                    "tcpSocket": {"port": "http"},
                                    "periodSeconds": 10,
                                    "failureThreshold": 60,
                                },
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "2Gi"},
                                    "limits": {"memory": "4Gi"},
                                },
                            }
                        ],
                        "volumes": [
                            {
                                "name": "config",
                                "configMap": {"name": f"{es_name}-config"},
                            },
                            {
                                "name": "certs",
                                "secret": {"secretName": elastic_tls_secret_name},
                            },
                        ],
                    },
                },
                "volumeClaimTemplates": [
                    {
                        "metadata": {"name": "data"},
                        "spec": {
                            "accessModes": ["ReadWriteOnce"],
                            "storageClassName": storage.get("className"),
                            "resources": {"requests": {"storage": sizes["elasticsearch"]}},
                        },
                    }
                ],
            },
        },
    ]

    if _component(config, "kibana")["enabled"] or _component(config, "logstash")["enabled"]:
        elastic_url = f"https://{es_name}:{ports['elasticsearch']}"
        elastic_bootstrap_script = "\n".join(
            [
                "set -eu",
                f'es_url="{elastic_url}"',
                "until curl --fail --silent --show-error "
                "--cacert /usr/share/elasticsearch/config/certs/ca.crt "
                '--user "elastic:$ELASTICSEARCH_PASSWORD" '
                '"$es_url/_cluster/health?wait_for_status=yellow" >/dev/null; do',
                "  sleep 5",
                "done",
                'if [ "$KIBANA_ENABLED" = "true" ]; then',
                "  curl --fail --silent --show-error "
                "--cacert /usr/share/elasticsearch/config/certs/ca.crt "
                '--user "elastic:$ELASTICSEARCH_PASSWORD" '
                "--header 'Content-Type: application/json' --request POST "
                '"$es_url/_security/user/kibana_system/_password" '
                '--data "{\\"password\\":\\"$KIBANA_SYSTEM_PASSWORD\\"}" >/dev/null',
                "fi",
                'if [ "$LOGSTASH_ENABLED" = "true" ]; then',
                "  curl --fail --silent --show-error "
                "--cacert /usr/share/elasticsearch/config/certs/ca.crt "
                '--user "elastic:$ELASTICSEARCH_PASSWORD" '
                "--header 'Content-Type: application/json' --request PUT "
                '"$es_url/_security/role/logstash_writer" '
                "--data "
                "'{\"cluster\":[\"manage_index_templates\",\"monitor\",\"manage_ilm\"],"
                "\"indices\":[{\"names\":[\"observeweaver-logs-*\"],"
                "\"privileges\":[\"write\",\"create\",\"delete\",\"create_index\",\"manage\","
                "\"manage_ilm\"]}]}' >/dev/null",
                "  curl --fail --silent --show-error "
                "--cacert /usr/share/elasticsearch/config/certs/ca.crt "
                '--user "elastic:$ELASTICSEARCH_PASSWORD" '
                "--header 'Content-Type: application/json' --request PUT "
                '"$es_url/_security/user/logstash_internal" '
                '--data "{\\"password\\":\\"$LOGSTASH_WRITER_PASSWORD\\",'
                '\\"roles\\":[\\"logstash_writer\\"],'
                '\\"full_name\\":\\"ObserveWeaver Logstash writer\\"}" >/dev/null',
                "fi",
            ]
        )
        items.append(
            {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {
                    "name": "observeweaver-elastic-bootstrap",
                    "namespace": namespace,
                },
                "spec": {
                    "backoffLimit": 6,
                    "ttlSecondsAfterFinished": 86400,
                    "template": {
                        "metadata": {
                            "labels": {
                                "app.kubernetes.io/name": "observeweaver-elastic-bootstrap"
                            }
                        },
                        "spec": {
                            "restartPolicy": "OnFailure",
                            "containers": [
                                {
                                    "name": "bootstrap",
                                    "image": DOCKER_IMAGE_LOCKS["elasticsearch"],
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": ["bash", "-c", elastic_bootstrap_script],
                                    "env": [
                                        {
                                            "name": "ELASTICSEARCH_PASSWORD",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": secret_name,
                                                    "key": "ELASTICSEARCH_PASSWORD",
                                                }
                                            },
                                        },
                                        {
                                            "name": "KIBANA_SYSTEM_PASSWORD",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": secret_name,
                                                    "key": "KIBANA_SYSTEM_PASSWORD",
                                                    "optional": True,
                                                }
                                            },
                                        },
                                        {
                                            "name": "LOGSTASH_WRITER_PASSWORD",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": secret_name,
                                                    "key": "LOGSTASH_WRITER_PASSWORD",
                                                    "optional": True,
                                                }
                                            },
                                        },
                                        {
                                            "name": "KIBANA_ENABLED",
                                            "value": str(
                                                _component(config, "kibana")["enabled"]
                                            ).lower(),
                                        },
                                        {
                                            "name": "LOGSTASH_ENABLED",
                                            "value": str(
                                                _component(config, "logstash")["enabled"]
                                            ).lower(),
                                        },
                                    ],
                                    "volumeMounts": [
                                        {
                                            "name": "certs",
                                            "mountPath": (
                                                "/usr/share/elasticsearch/config/certs"
                                            ),
                                            "readOnly": True,
                                        }
                                    ],
                                }
                            ],
                            "volumes": [
                                {
                                    "name": "certs",
                                    "secret": {"secretName": elastic_tls_secret_name},
                                }
                            ],
                        },
                    },
                },
            }
        )

    if _component(config, "kibana")["enabled"]:
        kibana_name = "observeweaver-kibana"
        kibana_env: list[dict[str, Any]] = [
            {"name": "SERVER_NAME", "value": kibana_name},
            {"name": "SERVER_HOST", "value": ANY_IPV4},
            {"name": "SERVER_PORT", "value": str(ports["kibana"])},
            {
                "name": "SERVER_PUBLICBASEURL",
                "value": (
                    f"{'http' if config['tls']['mode'] == 'disabled' else 'https'}://"
                    f"kibana.{domain}/"
                ),
            },
            {
                "name": "ELASTICSEARCH_HOSTS",
                "value": f"[\"https://{es_name}:{ports['elasticsearch']}\"]",
            },
            {"name": "ELASTICSEARCH_USERNAME", "value": "kibana_system"},
            {
                "name": "ELASTICSEARCH_SSL_CERTIFICATEAUTHORITIES",
                "value": "/usr/share/kibana/config/certs/ca.crt",
            },
            {"name": "ELASTICSEARCH_SSL_VERIFICATIONMODE", "value": "certificate"},
        ]
        for env_name, secret_key in (
            ("ELASTICSEARCH_PASSWORD", "KIBANA_SYSTEM_PASSWORD"),
            ("XPACK_SECURITY_ENCRYPTIONKEY", "KIBANA_SECURITY_ENCRYPTION_KEY"),
            ("XPACK_ENCRYPTEDSAVEDOBJECTS_ENCRYPTIONKEY", "KIBANA_ENCRYPTION_KEY"),
            ("XPACK_REPORTING_ENCRYPTIONKEY", "KIBANA_REPORTING_ENCRYPTION_KEY"),
        ):
            kibana_env.append(
                {
                    "name": env_name,
                    "valueFrom": {"secretKeyRef": {"name": secret_name, "key": secret_key}},
                }
            )
        items.extend(
            [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": kibana_name, "namespace": namespace},
                    "spec": {
                        "replicas": _replicas(config, "kibana"),
                        "selector": {"matchLabels": {"app.kubernetes.io/name": kibana_name}},
                        "template": {
                            "metadata": {"labels": {"app.kubernetes.io/name": kibana_name}},
                            "spec": {
                                "containers": [
                                    {
                                        "name": "kibana",
                                        "image": DOCKER_IMAGE_LOCKS["kibana"],
                                        "imagePullPolicy": "IfNotPresent",
                                        "env": kibana_env,
                                        "ports": [
                                            {"name": "http", "containerPort": ports["kibana"]}
                                        ],
                                        "volumeMounts": [
                                            {
                                                "name": "certs",
                                                "mountPath": "/usr/share/kibana/config/certs",
                                                "readOnly": True,
                                            }
                                        ],
                                        "readinessProbe": {
                                            "httpGet": {"path": "/api/status", "port": "http"},
                                            "periodSeconds": 10,
                                            "failureThreshold": 18,
                                        },
                                    }
                                ]
                            },
                            "volumes": [
                                {
                                    "name": "certs",
                                    "secret": {"secretName": elastic_tls_secret_name},
                                }
                            ],
                        },
                    },
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": kibana_name, "namespace": namespace},
                    "spec": {
                        "selector": {"app.kubernetes.io/name": kibana_name},
                        "ports": [{"name": "http", "port": ports["kibana"], "targetPort": "http"}],
                    },
                },
            ]
        )
        if ingress_enabled:
            ingress = {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "Ingress",
                "metadata": {"name": kibana_name, "namespace": namespace},
                "spec": {
                    "ingressClassName": ingress_class,
                    "rules": [
                        {
                            "host": f"kibana.{domain}",
                            "http": {
                                "paths": [
                                    {
                                        "path": "/",
                                        "pathType": "Prefix",
                                        "backend": {
                                            "service": {
                                                "name": kibana_name,
                                                "port": {"name": "http"},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                },
            }
            if tls_enabled:
                ingress["spec"]["tls"] = [
                    {"secretName": tls_secret_name, "hosts": [f"kibana.{domain}"]}
                ]
            items.append(ingress)

    if _component(config, "logstash")["enabled"]:
        logstash_name = "observeweaver-logstash"
        pipeline = f"""input {{
  beats {{ port => {ports['logstashBeats']} host => \"0.0.0.0\" }}
}}
output {{
  elasticsearch {{
    hosts => [\"https://{es_name}:{ports['elasticsearch']}\"]
    user => \"logstash_internal\"
    password => \"${{LOGSTASH_WRITER_PASSWORD}}\"
    ssl_enabled => true
    ssl_certificate_authorities => [\"/usr/share/logstash/certs/ca.crt\"]
    index => \"observeweaver-logs-%{{+YYYY.MM.dd}}\"
  }}
}}
"""
        items.extend(
            [
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": f"{logstash_name}-pipeline", "namespace": namespace},
                    "data": {"logstash.conf": pipeline},
                },
                {
                    "apiVersion": "apps/v1",
                    "kind": "StatefulSet",
                    "metadata": {"name": logstash_name, "namespace": namespace},
                    "spec": {
                        "serviceName": logstash_name,
                        "replicas": _replicas(config, "logstash"),
                        "podManagementPolicy": "Parallel",
                        "selector": {"matchLabels": {"app.kubernetes.io/name": logstash_name}},
                        "template": {
                            "metadata": {"labels": {"app.kubernetes.io/name": logstash_name}},
                            "spec": {
                                "containers": [
                                    {
                                        "name": "logstash",
                                        "image": DOCKER_IMAGE_LOCKS["logstash"],
                                        "imagePullPolicy": "IfNotPresent",
                                        "env": [
                                            {
                                                "name": "LOGSTASH_WRITER_PASSWORD",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "name": secret_name,
                                                        "key": "LOGSTASH_WRITER_PASSWORD",
                                                    }
                                                },
                                            },
                                            {"name": "LS_JAVA_OPTS", "value": "-Xms1g -Xmx1g"},
                                            {"name": "QUEUE_TYPE", "value": "persisted"},
                                        ],
                                        "ports": [
                                            {
                                                "name": "beats",
                                                "containerPort": ports["logstashBeats"],
                                            },
                                            {"name": "api", "containerPort": ports["logstashApi"]},
                                        ],
                                        "volumeMounts": [
                                            {
                                                "name": "pipeline",
                                                "mountPath": (
                                                    "/usr/share/logstash/pipeline/"
                                                    "logstash.conf"
                                                ),
                                                "subPath": "logstash.conf",
                                            },
                                            {
                                                "name": "certs",
                                                "mountPath": "/usr/share/logstash/certs",
                                                "readOnly": True,
                                            },
                                            {
                                                "name": "data",
                                                "mountPath": "/usr/share/logstash/data",
                                            },
                                        ],
                                        "readinessProbe": {
                                            "httpGet": {"path": "/", "port": "api"},
                                            "periodSeconds": 10,
                                            "failureThreshold": 18,
                                        },
                                    }
                                ],
                                "volumes": [
                                    {
                                        "name": "pipeline",
                                        "configMap": {"name": f"{logstash_name}-pipeline"},
                                    },
                                    {
                                        "name": "certs",
                                        "secret": {"secretName": elastic_tls_secret_name},
                                    },
                                ],
                            },
                        },
                        "volumeClaimTemplates": [
                            {
                                "metadata": {"name": "data"},
                                "spec": {
                                    "accessModes": ["ReadWriteOnce"],
                                    "storageClassName": storage.get("className"),
                                    "resources": {
                                        "requests": {"storage": sizes["logstash"]}
                                    },
                                },
                            }
                        ],
                    },
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": logstash_name, "namespace": namespace},
                    "spec": {
                        "selector": {"app.kubernetes.io/name": logstash_name},
                        "ports": [
                            {
                                "name": "beats",
                                "port": ports["logstashBeats"],
                                "targetPort": "beats",
                            },
                            {"name": "api", "port": ports["logstashApi"], "targetPort": "api"},
                        ],
                    },
                },
            ]
        )

    return {"apiVersion": "v1", "kind": "List", "items": items}


def _kafka_kubernetes_manifest(config: dict[str, Any]) -> dict[str, Any]:
    """Render a locked Kafka KRaft StatefulSet with durable storage."""
    if not _component(config, "kafka")["enabled"]:
        return {"apiVersion": "v1", "kind": "List", "items": []}

    namespace = config["deployment"]["namespace"]
    ports = config["network"]["ports"]
    storage = config["storage"]
    replicas = _replicas(config, "kafka")
    kafka_distribution = _kafka_distribution(config)
    name = "observeweaver-kafka"
    headless = f"{name}-headless"
    labels = {"app.kubernetes.io/name": name}
    controller_voters = ",".join(
        f"{index + 1}@{name}-{index}.{headless}.{namespace}.svc.cluster.local:"
        f"{ports['kafkaController']}"
        for index in range(replicas)
    )
    topic_replication = min(replicas, 3)
    min_isr = max(1, min(topic_replication, 2))
    startup_command = (
        "/etc/confluent/docker/run"
        if kafka_distribution == "confluent"
        else "/etc/kafka/docker/run"
    )
    probe_command = (
        "kafka-broker-api-versions"
        if kafka_distribution == "confluent"
        else "/opt/kafka/bin/kafka-broker-api-versions.sh"
    )
    startup = f"""set -eu
index="${{HOSTNAME##*-}}"
export KAFKA_NODE_ID="$((index + 1))"
export KAFKA_ADVERTISED_LISTENERS="INTERNAL://${{HOSTNAME}}.{headless}.{namespace}.svc.cluster.local:{ports['kafka']}"
exec {startup_command}
"""
    container = {
        "name": "kafka",
        "image": _kafka_image_lock(config),
        "imagePullPolicy": "IfNotPresent",
        "command": ["/bin/bash", "-ec"],
        "args": [startup],
        "env": [
            {"name": "CLUSTER_ID", "value": _kafka_cluster_id(config)},
            {"name": "KAFKA_PROCESS_ROLES", "value": "broker,controller"},
            {
                "name": "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP",
                "value": "INTERNAL:PLAINTEXT,CONTROLLER:PLAINTEXT",
            },
            {"name": "KAFKA_LISTENERS", "value": f"INTERNAL://:{ports['kafka']},CONTROLLER://:{ports['kafkaController']}"},
            {"name": "KAFKA_CONTROLLER_QUORUM_VOTERS", "value": controller_voters},
            {"name": "KAFKA_CONTROLLER_LISTENER_NAMES", "value": "CONTROLLER"},
            {"name": "KAFKA_INTER_BROKER_LISTENER_NAME", "value": "INTERNAL"},
            {"name": "KAFKA_LOG_DIRS", "value": "/var/lib/kafka/data"},
            {"name": "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR", "value": str(topic_replication)},
            {
                "name": "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR",
                "value": str(topic_replication),
            },
            {"name": "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR", "value": str(min_isr)},
            {
                "name": "KAFKA_SHARE_COORDINATOR_STATE_TOPIC_REPLICATION_FACTOR",
                "value": str(topic_replication),
            },
            {"name": "KAFKA_SHARE_COORDINATOR_STATE_TOPIC_MIN_ISR", "value": str(min_isr)},
            {"name": "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS", "value": "0"},
        ],
        "ports": [
            {"name": "broker", "containerPort": ports["kafka"]},
            {"name": "controller", "containerPort": ports["kafkaController"]},
        ],
        "volumeMounts": [{"name": "data", "mountPath": "/var/lib/kafka/data"}],
        "readinessProbe": {
            "exec": {
                "command": [
                    "/bin/bash",
                    "-ec",
                    f"{probe_command} "
                    f"--bootstrap-server 127.0.0.1:{ports['kafka']} >/dev/null",
                ]
            },
            "initialDelaySeconds": 20,
            "periodSeconds": 10,
            "failureThreshold": 12,
        },
        "livenessProbe": {
            "tcpSocket": {"port": "broker"},
            "initialDelaySeconds": 60,
            "periodSeconds": 20,
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": False,
            "capabilities": {"drop": ["ALL"]},
        },
    }
    stateful_set = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "serviceName": headless,
            "replicas": replicas,
            "podManagementPolicy": "Parallel",
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "terminationGracePeriodSeconds": 120,
                    "securityContext": {"fsGroup": 1000, "runAsNonRoot": True},
                    "containers": [container],
                },
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "data"},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "storageClassName": storage.get("className"),
                        "resources": {"requests": {"storage": storage["sizes"]["kafka"]}},
                    },
                }
            ],
        },
    }
    items: list[dict[str, Any]] = [
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": headless, "namespace": namespace, "labels": labels},
            "spec": {
                "clusterIP": "None",
                "publishNotReadyAddresses": True,
                "selector": labels,
                "ports": [
                    {"name": "broker", "port": ports["kafka"], "targetPort": "broker"},
                    {
                        "name": "controller",
                        "port": ports["kafkaController"],
                        "targetPort": "controller",
                    },
                ],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": namespace, "labels": labels},
            "spec": {
                "selector": labels,
                "ports": [{"name": "broker", "port": ports["kafka"], "targetPort": "broker"}],
            },
        },
        stateful_set,
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": f"{name}-private", "namespace": namespace},
            "spec": {
                "podSelector": {"matchLabels": labels},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [{"podSelector": {}}],
                        "ports": [
                            {"protocol": "TCP", "port": ports["kafka"]},
                            {"protocol": "TCP", "port": ports["kafkaController"]},
                        ],
                    }
                ],
            },
        },
    ]
    return {"apiVersion": "v1", "kind": "List", "items": items}


def _kubernetes_values(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    storage = config["storage"]
    sizes = storage["sizes"]
    ports = config["network"]["ports"]
    domain = config["network"]["domain"]
    ingress_enabled = config["network"]["ingress"]["enabled"]
    ingress_class = config["network"]["ingress"].get("className", "")
    tls_enabled = ingress_enabled and config["tls"]["mode"] != "disabled"
    tls_secret_name = config["tls"]["secretName"]
    secret_name = config["security"].get("kubernetesSecretName", "observeweaver-secrets")

    prometheus = {
        "grafana": {
            "enabled": _component(config, "grafana")["enabled"],
            "replicas": _replicas(config, "grafana"),
            "image": {"tag": _component(config, "grafana")["version"]},
            "admin": {
                "existingSecret": secret_name,
                "userKey": "GRAFANA_ADMIN_USER",
                "passwordKey": "GRAFANA_ADMIN_PASSWORD",
            },
            "persistence": {
                "enabled": _replicas(config, "grafana") == 1,
                "storageClassName": storage.get("className"),
                "size": sizes["grafana"],
            },
            "service": {
                "port": ports["grafana"],
                "targetPort": 3000,
            },
            "ingress": {
                "enabled": ingress_enabled,
                "ingressClassName": ingress_class,
                "hosts": [f"grafana.{domain}"],
            },
            "sidecar": {
                "datasources": {
                    "defaultDatasourceEnabled": _component(config, "prometheus")["enabled"]
                }
            },
        },
        "prometheus": {
            "enabled": _component(config, "prometheus")["enabled"],
            "service": {
                "port": ports["prometheus"],
                "targetPort": 9090,
            },
            "prometheusSpec": {
                "replicas": _replicas(config, "prometheus"),
                "image": {"tag": f"v{_component(config, 'prometheus')['version']}"},
                "retention": f"{config['retention']['metricsDays']}d",
                "storageSpec": {
                    "volumeClaimTemplate": {
                        "spec": {
                            "storageClassName": storage.get("className"),
                            "accessModes": ["ReadWriteOnce"],
                            "resources": {"requests": {"storage": sizes["prometheus"]}},
                        }
                    }
                },
            },
        },
        "alertmanager": {
            "enabled": _component(config, "alertmanager")["enabled"],
            "service": {
                "port": ports["alertmanager"],
                "targetPort": 9093,
                "clusterPort": ports["alertmanagerCluster"],
            },
            "alertmanagerSpec": {
                "replicas": _replicas(config, "alertmanager"),
                "image": {"tag": f"v{_component(config, 'alertmanager')['version']}"},
                "storage": {
                    "volumeClaimTemplate": {
                        "spec": {
                            "storageClassName": storage.get("className"),
                            "accessModes": ["ReadWriteOnce"],
                            "resources": {"requests": {"storage": sizes["alertmanager"]}},
                        }
                    }
                },
            },
        },
    }
    if tls_enabled and _component(config, "grafana")["enabled"]:
        prometheus["grafana"]["ingress"]["tls"] = [
            {
                "secretName": tls_secret_name,
                "hosts": [f"grafana.{domain}"],
            }
        ]
    if _component(config, "grafana")["enabled"] and _replicas(config, "grafana") > 1:
        prometheus["grafana"]["env"] = {
            "GF_DATABASE_TYPE": "postgres",
            "GF_DATABASE_SSL_MODE": "require",
        }
        prometheus["grafana"]["envValueFrom"] = {
            "GF_DATABASE_HOST": {
                "secretKeyRef": {"name": secret_name, "key": "GRAFANA_DATABASE_HOST"}
            },
            "GF_DATABASE_NAME": {
                "secretKeyRef": {"name": secret_name, "key": "GRAFANA_DATABASE_NAME"}
            },
            "GF_DATABASE_USER": {
                "secretKeyRef": {"name": secret_name, "key": "GRAFANA_DATABASE_USER"}
            },
            "GF_DATABASE_PASSWORD": {
                "secretKeyRef": {"name": secret_name, "key": "POSTGRES_PASSWORD"}
            },
        }

    otel = {
        "mode": "deployment",
        "replicaCount": _replicas(config, "opentelemetry"),
        "image": {
            "repository": "otel/opentelemetry-collector-contrib",
            "tag": _component(config, "opentelemetry")["version"],
        },
        "ports": {
            "otlp": {
                "enabled": True,
                "containerPort": ports["otlpGrpc"],
                "servicePort": ports["otlpGrpc"],
            },
            "otlp-http": {
                "enabled": True,
                "containerPort": ports["otlpHttp"],
                "servicePort": ports["otlpHttp"],
            },
            "metrics": {
                "enabled": True,
                "containerPort": ports["otelPrometheus"],
                "servicePort": ports["otelPrometheus"],
            },
            "internal-metrics": {
                "enabled": True,
                "containerPort": ports["otelMetrics"],
                "servicePort": ports["otelMetrics"],
            },
            "health": {
                "enabled": True,
                "containerPort": ports["otelHealth"],
                "servicePort": ports["otelHealth"],
            },
            "jaeger-compact": {"enabled": False},
            "jaeger-thrift": {"enabled": False},
            "jaeger-grpc": {"enabled": False},
            "zipkin": {"enabled": False},
        },
        "config": {
            "receivers": {
                "jaeger": None,
                "zipkin": None,
                "otlp": {
                    "protocols": {
                        "grpc": {"endpoint": f"0.0.0.0:{ports['otlpGrpc']}"},
                        "http": {"endpoint": f"0.0.0.0:{ports['otlpHttp']}"},
                    }
                },
            },
            "processors": {
                "memory_limiter": {
                    "check_interval": "1s",
                    "limit_percentage": 75,
                    "spike_limit_percentage": 15,
                },
                "batch": {},
            },
            "exporters": {
                "prometheus": {"endpoint": f"0.0.0.0:{ports['otelPrometheus']}"},
                "debug": {"verbosity": "basic"},
            },
            "service": {
                "telemetry": {
                    "metrics": {
                        "readers": [
                            {
                                "pull": {
                                    "exporter": {
                                        "prometheus": {
                                            "host": ANY_IPV4,
                                            "port": ports["otelMetrics"],
                                        }
                                    }
                                }
                            }
                        ]
                    }
                },
                "pipelines": {
                    "metrics": {
                        "receivers": ["otlp"],
                        "processors": ["memory_limiter", "batch"],
                        "exporters": ["prometheus"],
                    },
                    "logs": {
                        "receivers": ["otlp"],
                        "processors": ["memory_limiter", "batch"],
                        "exporters": ["debug"],
                    },
                    "traces": {
                        "receivers": ["otlp"],
                        "processors": ["memory_limiter", "batch"],
                        "exporters": ["debug"],
                    },
                },
            },
        },
        "serviceMonitor": {
            "enabled": any(
                _component(config, name)["enabled"]
                for name in ("prometheus", "alertmanager", "grafana")
            ),
            "extraLabels": {"release": "observeweaver-monitoring"},
            "metricsEndpoints": [{"port": "metrics"}],
        },
    }

    graylog = {
        "version": _component(config, "graylog")["version"],
        "global": {"storageClass": storage.get("className")},
        "graylog": {
            "enabled": _component(config, "graylog")["enabled"],
            "enterprise": False,
            "replicas": _replicas(config, "graylog"),
            "image": {
                "repository": "graylog/graylog",
                "tag": _component(config, "graylog")["version"],
            },
            "config": {
                "network": {"externalUri": f"graylog.{domain}"},
                "email": {
                    "webInterfaceUrl": (
                        f"{'http' if config['tls']['mode'] == 'disabled' else 'https'}"
                        f"://graylog.{domain}/"
                    )
                },
                "messageJournal": {
                    "enabled": "true",
                    "maxAge": f"{config['retention']['logsDays']}d",
                },
            },
            "env": {
                "GRAYLOG_HTTP_BIND_ADDRESS": (f"{ANY_IPV4}:{ports['graylogHttp']}"),
                "GRAYLOG_ELASTICSEARCH_REPLICAS": (
                    "1" if config["deployment"]["mode"] == "cluster" else "0"
                ),
                "GRAYLOG_ROTATION_STRATEGY": "time",
                "GRAYLOG_ELASTICSEARCH_MAX_TIME_PER_INDEX": "1d",
                "GRAYLOG_RETENTION_STRATEGY": "delete",
                "GRAYLOG_ELASTICSEARCH_MAX_NUMBER_OF_INDICES": str(config["retention"]["logsDays"]),
            },
            "persistence": {
                "enabled": True,
                "storageClass": storage.get("className"),
                "size": sizes["graylogJournal"],
            },
            "service": {
                "ports": {
                    "app": ports["graylogHttp"],
                }
            },
            "inputs": [
                {
                    "name": "gelf-tcp",
                    "port": ports["graylogGelfTcp"],
                    "targetPort": ports["graylogGelfTcp"],
                    "protocol": "TCP",
                },
                {
                    "name": "gelf-udp",
                    "port": ports["graylogGelfUdp"],
                    "targetPort": ports["graylogGelfUdp"],
                    "protocol": "UDP",
                },
                {
                    "name": "beats",
                    "port": ports["graylogBeats"],
                    "targetPort": ports["graylogBeats"],
                    "protocol": "TCP",
                },
                {
                    "name": "syslog-tcp",
                    "port": ports["graylogSyslogTcp"],
                    "targetPort": ports["graylogSyslogTcp"],
                    "protocol": "TCP",
                },
                {
                    "name": "syslog-udp",
                    "port": ports["graylogSyslogUdp"],
                    "targetPort": ports["graylogSyslogUdp"],
                    "protocol": "UDP",
                },
            ],
        },
        "datanode": {
            "enabled": _component(config, "opensearch")["enabled"],
            "replicas": _replicas(config, "opensearch"),
            "config": {
                "opensearchHeap": _component(config, "opensearch")
                .get("javaOpts", "-Xms2g -Xmx2g")
                .split("-Xmx")[-1],
            },
            "env": {
                "GRAYLOG_DATANODE_DATANODE_HTTP_PORT": str(ports["graylogDataNode"]),
                "GRAYLOG_DATANODE_OPENSEARCH_HTTP_PORT": str(ports["opensearch"]),
                "GRAYLOG_DATANODE_OPENSEARCH_TRANSPORT_PORT": str(ports["opensearchTransport"]),
            },
            "service": {
                "ports": {
                    "api": ports["graylogDataNode"],
                    "data": ports["opensearch"],
                    "config": ports["opensearchTransport"],
                }
            },
            "persistence": {
                "enabled": True,
                "data": {
                    "enabled": True,
                    "storageClass": storage.get("className"),
                    "size": sizes["opensearch"],
                },
            },
        },
        "mongodb": {
            "communityResource": {"enabled": True},
            "version": config["dependencies"]["mongodb"]["version"],
            "replicas": 3 if config["deployment"]["mode"] == "cluster" else 1,
            "arbiters": 0,
            "persistence": {
                "storageClass": storage.get("className"),
                "size": {"data": sizes["mongodb"], "logs": "2Gi"},
            },
        },
        "ingress": {
            "enabled": ingress_enabled,
            "config": {"defaultBackend": {"enabled": False}},
            "web": {
                "enabled": ingress_enabled,
                "className": ingress_class,
                "hosts": [
                    {
                        "host": f"graylog.{domain}",
                        "paths": [{"path": "/", "pathType": "Prefix"}],
                    }
                ],
            },
        },
    }
    if tls_enabled and _component(config, "graylog")["enabled"]:
        graylog["ingress"]["web"]["tls"] = [
            {
                "secretName": tls_secret_name,
                "hosts": [f"graylog.{domain}"],
            }
        ]
    zabbix_enabled = _component(config, "zabbix")["enabled"]
    zabbix_replicas = _replicas(config, "zabbix")
    zabbix_external_database = config["dependencies"]["zabbixPostgresql"]["external"]
    zabbix_ha = (
        zabbix_enabled
        and config["deployment"]["mode"] == "cluster"
        and config["deployment"]["engine"] in {"k3s", "rke2"}
        and zabbix_replicas > 1
    )
    zabbix = {
        "zabbixImageTag": f"ubuntu-{_component(config, 'zabbix')['version']}",
        "postgresAccess": {
            "existingSecretName": config["security"]["kubernetesSecretName"],
            "secretHostKey": "ZABBIX_DATABASE_HOST" if zabbix_external_database else "",
            "secretPortKey": "ZABBIX_DATABASE_PORT" if zabbix_external_database else "",
            "secretUserKey": "ZABBIX_DATABASE_USER",
            "secretPasswordKey": "ZABBIX_DATABASE_PASSWORD",
            "secretDBKey": "ZABBIX_DATABASE_NAME",
            "host": "",
            "port": "5432",
            "user": "zabbix",
            "database": "zabbix",
        },
        "zabbixServer": {
            "enabled": zabbix_enabled,
            "replicaCount": zabbix_replicas,
            "zabbixServerHA": {"enabled": zabbix_ha},
            "service": {"type": "ClusterIP"},
        },
        "zabbixWeb": {
            "enabled": zabbix_enabled,
            "replicaCount": zabbix_replicas,
            "service": {"type": "ClusterIP"},
        },
        "ingress": {
            "enabled": ingress_enabled and zabbix_enabled,
            "ingressClassName": ingress_class,
            "annotations": {},
            "hosts": [
                {
                    "host": f"zabbix.{domain}",
                    "paths": [{"path": "/", "pathType": "Prefix"}],
                }
            ],
            "tls": (
                [
                    {
                        "secretName": tls_secret_name,
                        "hosts": [f"zabbix.{domain}"],
                    }
                ]
                if tls_enabled and zabbix_enabled
                else []
            ),
        },
        "postgresql": {
            "enabled": zabbix_enabled and not zabbix_external_database,
            "image": {
                "repository": "postgres",
                "tag": config["dependencies"]["postgresql"]["version"],
            },
            "persistence": {
                "enabled": zabbix_enabled and not zabbix_external_database,
                "storageSize": sizes["zabbixPostgresql"],
                "storageClass": storage.get("className", ""),
            },
        },
    }
    return {
        "kube-prometheus-stack": prometheus,
        "opentelemetry-collector": otel,
        "graylog": graylog,
        "zabbix": zabbix,
        "redis": _redis_kubernetes_manifest(config),
        "elastic-stack": _elastic_kubernetes_manifest(config),
        "kafka-stack": _kafka_kubernetes_manifest(config),
        "public-tls": _public_tls_manifest(config),
    }


def _docker_cluster_node_files(config: dict[str, Any], node: dict[str, Any]) -> dict[str, str]:
    ports = config["network"]["ports"]
    metrics_nodes = [item for item in config["nodes"] if "metrics" in item["roles"]]
    telemetry_nodes = [item for item in config["nodes"] if "telemetry" in item["roles"]]
    log_nodes = [item for item in config["nodes"] if "logs" in item["roles"]]
    data_nodes = [item for item in config["nodes"] if "data" in item["roles"]]
    eligible_nodes = {
        "prometheus": metrics_nodes,
        "alertmanager": metrics_nodes,
        "grafana": metrics_nodes,
        "opentelemetry": telemetry_nodes,
        "zabbix": metrics_nodes,
        "graylog": log_nodes,
        "opensearch": data_nodes,
        "elasticsearch": data_nodes,
        "kibana": [item for item in config["nodes"] if "ingress" in item["roles"]],
        "logstash": log_nodes,
        "redis": data_nodes,
        "kafka": data_nodes,
    }
    component_nodes = {
        name: nodes[: _replicas(config, name)] if _component(config, name)["enabled"] else []
        for name, nodes in eligible_nodes.items()
    }
    mongodb_nodes = (
        data_nodes[: 3 if config["deployment"]["mode"] == "cluster" else 1]
        if _component(config, "graylog")["enabled"]
        else []
    )
    active_profiles = [
        profile for profile, assigned_nodes in component_nodes.items() if node in assigned_nodes
    ]
    if _component(config, "graylog")["enabled"] and node in mongodb_nodes:
        active_profiles.append("mongodb")
    zabbix_nodes = component_nodes["zabbix"]
    zabbix_external_database = config["dependencies"]["zabbixPostgresql"]["external"]
    if zabbix_nodes and node == zabbix_nodes[0] and not zabbix_external_database:
        active_profiles.append("zabbix-postgresql")
    node_env = {
        "NODE_NAME": node["name"],
        "NODE_ADDRESS": node["address"],
        "NODE_ENDPOINT_ADDRESS": _endpoint_host(node["address"]),
        "OBSERVEWEAVER_DOMAIN": config["network"]["domain"],
        "OBSERVEWEAVER_SCHEME": "https" if config["tls"]["mode"] != "disabled" else "http",
        "PROMETHEUS_VERSION": _component(config, "prometheus")["version"],
        "PROMETHEUS_ENABLED": str(_component(config, "prometheus")["enabled"]).lower(),
        "ALERTMANAGER_VERSION": _component(config, "alertmanager")["version"],
        "ALERTMANAGER_ENABLED": str(_component(config, "alertmanager")["enabled"]).lower(),
        "GRAFANA_VERSION": _component(config, "grafana")["version"],
        "GRAFANA_ENABLED": str(_component(config, "grafana")["enabled"]).lower(),
        "OTELCOL_VERSION": _component(config, "opentelemetry")["version"],
        "OTELCOL_ENABLED": str(_component(config, "opentelemetry")["enabled"]).lower(),
        "GRAYLOG_VERSION": _component(config, "graylog")["version"],
        "GRAYLOG_ENABLED": str(_component(config, "graylog")["enabled"]).lower(),
        "OPENSEARCH_VERSION": _component(config, "opensearch")["version"],
        "OPENSEARCH_ENABLED": str(_component(config, "opensearch")["enabled"]).lower(),
        "ELASTICSEARCH_VERSION": _component(config, "elasticsearch")["version"],
        "ELASTICSEARCH_ENABLED": str(_component(config, "elasticsearch")["enabled"]).lower(),
        "ELASTICSEARCH_SECURITY_ENABLED": "false",
        "KIBANA_VERSION": _component(config, "kibana")["version"],
        "KIBANA_ENABLED": str(_component(config, "kibana")["enabled"]).lower(),
        "LOGSTASH_VERSION": _component(config, "logstash")["version"],
        "LOGSTASH_ENABLED": str(_component(config, "logstash")["enabled"]).lower(),
        "REDIS_VERSION": _component(config, "redis")["version"],
        "REDIS_ENABLED": str(_component(config, "redis")["enabled"]).lower(),
        "KAFKA_DISTRIBUTION": _kafka_distribution(config),
        "KAFKA_VERSION": _component(config, "kafka")["version"],
        "KAFKA_ENABLED": str(_component(config, "kafka")["enabled"]).lower(),
        "MONGODB_VERSION": config["dependencies"]["mongodb"]["version"],
        "POSTGRES_VERSION": config["dependencies"]["postgresql"]["version"],
        "PROMETHEUS_IMAGE": DOCKER_IMAGE_LOCKS["prometheus"],
        "ALERTMANAGER_IMAGE": DOCKER_IMAGE_LOCKS["alertmanager"],
        "GRAFANA_IMAGE": DOCKER_IMAGE_LOCKS["grafana"],
        "OTELCOL_IMAGE": DOCKER_IMAGE_LOCKS["opentelemetry"],
        "POSTGRES_IMAGE": DOCKER_IMAGE_LOCKS["postgresql"],
        "ZABBIX_SERVER_IMAGE": DOCKER_IMAGE_LOCKS["zabbixServer"],
        "ZABBIX_WEB_IMAGE": DOCKER_IMAGE_LOCKS["zabbixWeb"],
        "MONGODB_IMAGE": DOCKER_IMAGE_LOCKS["mongodb"],
        "OPENSEARCH_IMAGE": DOCKER_IMAGE_LOCKS["opensearch"],
        "ELASTICSEARCH_IMAGE": DOCKER_IMAGE_LOCKS["elasticsearch"],
        "KIBANA_IMAGE": DOCKER_IMAGE_LOCKS["kibana"],
        "LOGSTASH_IMAGE": DOCKER_IMAGE_LOCKS["logstash"],
        "GRAYLOG_IMAGE": DOCKER_IMAGE_LOCKS["graylog"],
        "REDIS_IMAGE": DOCKER_IMAGE_LOCKS["redis"],
        "KAFKA_IMAGE": _kafka_image_lock(config),
        "PROMETHEUS_PORT": ports["prometheus"],
        "ALERTMANAGER_PORT": ports["alertmanager"],
        "ALERTMANAGER_CLUSTER_PORT": ports["alertmanagerCluster"],
        "GRAFANA_PORT": ports["grafana"],
        "OTLP_GRPC_PORT": ports["otlpGrpc"],
        "OTLP_HTTP_PORT": ports["otlpHttp"],
        "OTEL_HEALTH_PORT": ports["otelHealth"],
        "OTEL_METRICS_PORT": ports["otelMetrics"],
        "OTEL_PROMETHEUS_PORT": ports["otelPrometheus"],
        "ZABBIX_VERSION": _component(config, "zabbix")["version"],
        "ZABBIX_SERVER_PORT": ports["zabbixServer"],
        "ZABBIX_WEB_PORT": ports["zabbixWeb"],
        "GRAYLOG_HTTP_PORT": ports["graylogHttp"],
        "GRAYLOG_BEATS_PORT": ports["graylogBeats"],
        "GRAYLOG_GELF_TCP_PORT": ports["graylogGelfTcp"],
        "GRAYLOG_GELF_UDP_PORT": ports["graylogGelfUdp"],
        "GRAYLOG_SYSLOG_TCP_PORT": ports["graylogSyslogTcp"],
        "GRAYLOG_SYSLOG_UDP_PORT": ports["graylogSyslogUdp"],
        "OPENSEARCH_PORT": ports["opensearch"],
        "OPENSEARCH_TRANSPORT_PORT": ports["opensearchTransport"],
        "ELASTICSEARCH_PORT": ports["elasticsearch"],
        "ELASTICSEARCH_TRANSPORT_PORT": ports["elasticsearchTransport"],
        "KIBANA_PORT": ports["kibana"],
        "LOGSTASH_BEATS_PORT": ports["logstashBeats"],
        "LOGSTASH_API_PORT": ports["logstashApi"],
        "MONGODB_PORT": ports["mongodb"],
        "REDIS_PORT": ports["redis"],
        "REDIS_SENTINEL_PORT": ports["redisSentinel"],
        "KAFKA_PORT": ports["kafka"],
        "KAFKA_CONTROLLER_PORT": ports["kafkaController"],
        "KAFKA_NODE_ID": (
            component_nodes["kafka"].index(node) + 1
            if node in component_nodes["kafka"]
            else ""
        ),
        "KAFKA_CLUSTER_ID": _kafka_cluster_id(config),
        "KAFKA_CONTROLLER_QUORUM_VOTERS": ",".join(
            f"{index + 1}@{item['name']}:{ports['kafkaController']}"
            for index, item in enumerate(component_nodes["kafka"])
        ),
        "KAFKA_ADVERTISED_ADDRESS": node["address"],
        "KAFKA_REPLICATION_FACTOR": min(len(component_nodes["kafka"]), 3) or 1,
        "KAFKA_MIN_ISR": (
            max(1, min(len(component_nodes["kafka"]), 2))
            if component_nodes["kafka"]
            else 1
        ),
        "REDIS_PRIMARY_HOST": (
            component_nodes["redis"][0]["name"] if component_nodes["redis"] else ""
        ),
        "REDIS_PRIMARY_NODE": (
            component_nodes["redis"][0]["name"] if component_nodes["redis"] else ""
        ),
        "REDIS_SENTINEL_QUORUM": 2 if len(component_nodes["redis"]) > 1 else 1,
        "PROMETHEUS_RETENTION": f"{config['retention']['metricsDays']}d",
        "GRAYLOG_RETENTION_DAYS": config["retention"]["logsDays"],
        "GRAYLOG_ELASTICSEARCH_REPLICAS": (1 if config["deployment"]["mode"] == "cluster" else 0),
        "OPENSEARCH_JAVA_OPTS": _component(config, "opensearch").get("javaOpts", "-Xms2g -Xmx2g"),
        "OPENSEARCH_SEED_HOSTS": ",".join(
            _host_port(item["name"], ports["opensearchTransport"])
            for item in component_nodes["opensearch"]
        ),
        "OPENSEARCH_INITIAL_CLUSTER_MANAGER_NODES": ",".join(
            item["name"] for item in component_nodes["opensearch"]
        ),
        "ELASTICSEARCH_SEED_HOSTS": ",".join(
            _host_port(item["name"], ports["elasticsearchTransport"])
            for item in component_nodes["elasticsearch"]
        ),
        "ELASTICSEARCH_INITIAL_MASTER_NODES": ",".join(
            item["name"] for item in component_nodes["elasticsearch"]
        ),
        "ELASTICSEARCH_HOSTS": "["
        + ",".join(
            f'"http://{item["name"]}:{ports["elasticsearch"]}"'
            for item in component_nodes["elasticsearch"]
        )
        + "]",
        "ALERTMANAGER_PEERS": ",".join(
            f"{item['name']}:{ports['alertmanagerCluster']}"
            for item in component_nodes["alertmanager"]
            if item["name"] != node["name"]
        ),
        "COMPOSE_PROFILES": ",".join(active_profiles),
    }
    if not zabbix_external_database:
        node_env["ZABBIX_DATABASE_HOST"] = zabbix_nodes[0]["address"] if zabbix_nodes else ""
    env_text = (
        "# Generated by owctl; contains no secret values.\n"
        + "\n".join(f"{key}={value}" for key, value in node_env.items())
        + "\n"
    )

    scrape_configs = []
    if component_nodes["prometheus"]:
        scrape_configs.append(
            {
                "job_name": "prometheus",
                "static_configs": [
                    {
                        "targets": [
                            _host_port(item["address"], ports["prometheus"])
                            for item in component_nodes["prometheus"]
                        ]
                    }
                ],
            }
        )
    if component_nodes["opentelemetry"]:
        scrape_configs.extend(
            [
                {
                    "job_name": "otel-collector-internal",
                    "static_configs": [
                        {
                            "targets": [
                                _host_port(item["address"], ports["otelMetrics"])
                                for item in component_nodes["opentelemetry"]
                            ]
                        }
                    ],
                },
                {
                    "job_name": "otel-exported-metrics",
                    "static_configs": [
                        {
                            "targets": [
                                _host_port(item["address"], ports["otelPrometheus"])
                                for item in component_nodes["opentelemetry"]
                            ]
                        }
                    ],
                },
            ]
        )
    prometheus = {
        "global": {"scrape_interval": "15s", "evaluation_interval": "15s"},
        "scrape_configs": scrape_configs,
    }
    if component_nodes["alertmanager"]:
        prometheus["alerting"] = {
            "alertmanagers": [
                {
                    "static_configs": [
                        {
                            "targets": [
                                _host_port(item["address"], ports["alertmanager"])
                                for item in component_nodes["alertmanager"]
                            ]
                        }
                    ]
                }
            ]
        }
    alertmanager = {
        "global": {"resolve_timeout": "5m"},
        "route": {
            "receiver": "default",
            "group_by": ["alertname", "cluster", "service"],
            "group_wait": "30s",
            "group_interval": "5m",
            "repeat_interval": "4h",
        },
        "receivers": [{"name": "default"}],
    }
    otel = {
        "extensions": {"health_check": {"endpoint": f"0.0.0.0:{ports['otelHealth']}"}},
        "receivers": {
            "otlp": {
                "protocols": {
                    "grpc": {"endpoint": f"0.0.0.0:{ports['otlpGrpc']}"},
                    "http": {"endpoint": f"0.0.0.0:{ports['otlpHttp']}"},
                }
            }
        },
        "processors": {
            "memory_limiter": {
                "check_interval": "1s",
                "limit_percentage": 75,
                "spike_limit_percentage": 15,
            },
            "batch": {},
        },
        "exporters": {
            "prometheus": {"endpoint": f"0.0.0.0:{ports['otelPrometheus']}"},
            "debug": {"verbosity": "basic"},
        },
        "service": {
            "extensions": ["health_check"],
            "telemetry": {
                "metrics": {
                    "readers": [
                        {
                            "pull": {
                                "exporter": {
                                    "prometheus": {
                                        "host": ANY_IPV4,
                                        "port": ports["otelMetrics"],
                                    }
                                }
                            }
                        }
                    ]
                }
            },
            "pipelines": {
                "metrics": {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "batch"],
                    "exporters": ["prometheus"],
                },
                "logs": {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "batch"],
                    "exporters": ["debug"],
                },
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "batch"],
                    "exporters": ["debug"],
                },
            },
        },
    }
    mongo_hosts = ",".join(f"{item['name']}:{ports['mongodb']}" for item in mongodb_nodes)
    search_hosts = ",".join(
        f"http://{item['name']}:{ports['opensearch']}" for item in component_nodes["opensearch"]
    )
    datasource_node = (
        node
        if node in component_nodes["prometheus"]
        else component_nodes["prometheus"][0]
        if component_nodes["prometheus"]
        else None
    )
    prometheus_datasources = (
        [
            {
                "name": "Prometheus",
                "uid": "prometheus",
                "type": "prometheus",
                "access": "proxy",
                "url": "http://"
                + _host_port(
                    datasource_node["address"],
                    ports["prometheus"],
                ),
                "isDefault": True,
                "editable": False,
                "jsonData": {
                    "httpMethod": "POST",
                    "prometheusType": "Prometheus",
                    "timeInterval": "15s",
                },
            }
        ]
        if datasource_node
        else []
    )
    datasource = {
        "apiVersion": 1,
        "deleteDatasources": [{"name": "Prometheus", "orgId": 1}],
        "datasources": prometheus_datasources,
    }
    extra_hosts = {item["name"]: item["address"] for item in config["nodes"]}
    override: dict[str, Any] = {
        "services": {
            service: {"extra_hosts": extra_hosts}
            for service in (
                "prometheus",
                "alertmanager",
                "grafana",
                "otel-collector",
                "zabbix-postgresql",
                "zabbix-server",
                "zabbix-web",
                "mongodb",
        "opensearch",
                "elasticsearch",
                "kibana",
                "logstash",
                "graylog",
                "redis",
                "redis-sentinel",
                "kafka",
            )
        }
    }
    if component_nodes["graylog"]:
        override["services"]["graylog"]["environment"] = {
            "GRAYLOG_MONGODB_URI": (
                "mongodb://graylog:${MONGODB_ROOT_PASSWORD}@"
                f"{mongo_hosts}/graylog?authSource=admin&replicaSet=observeweaver"
            ),
            "GRAYLOG_ELASTICSEARCH_HOSTS": search_hosts,
        }
    logstash_hosts = ",".join(
        f"http://{item['name']}:{ports['elasticsearch']}"
        for item in component_nodes["elasticsearch"]
    )
    logstash_hosts_config = ", ".join(
        '"' + host + '"' for host in logstash_hosts.split(",") if host
    )
    logstash = f"""input {{
  beats {{ port => {ports['logstashBeats']} host => \"0.0.0.0\" }}
}}
output {{
  elasticsearch {{
    hosts => [{logstash_hosts_config}]
    user => \"elastic\"
    password => \"${{ELASTICSEARCH_PASSWORD}}\"
    index => \"observeweaver-logs-%{{+YYYY.MM.dd}}\"
  }}
}}
"""
    if mongodb_nodes and node["name"] == mongodb_nodes[0]["name"]:
        override["services"]["mongodb"] = {
            "extra_hosts": extra_hosts,
            "environment": {
                "MONGO_INITDB_ROOT_USERNAME": "graylog",
                "MONGO_INITDB_ROOT_PASSWORD": "${MONGODB_ROOT_PASSWORD}",
                "MONGO_INITDB_DATABASE": "graylog",
            },
        }
    return {
        ".env.generated": env_text,
        "prometheus.yml": yaml.safe_dump(prometheus, sort_keys=False),
        "alertmanager.yml": yaml.safe_dump(alertmanager, sort_keys=False),
        "otel-collector.yml": yaml.safe_dump(otel, sort_keys=False),
        "grafana-datasources.yml": yaml.safe_dump(datasource, sort_keys=False),
        "logstash.conf": logstash,
        "compose.override.generated.yml": yaml.safe_dump(override, sort_keys=False),
    }


def render(config: dict[str, Any], output_root: str | Path) -> list[Path]:
    environment = config["metadata"].get("environment", "production")
    root = Path(output_root) / environment
    created: list[Path] = []

    artifacts = {
        root / "docker" / ".env.generated": _docker_env(config),
        root / "ansible" / "inventory.generated.ini": _inventory(config),
        root / "ansible" / "group_vars.generated.yml": _group_vars(config),
    }
    for path, content in artifacts.items():
        _write(path, content)
        created.append(path)

    for filename, content in _docker_standalone_configs(config).items():
        path = root / "docker" / "configs" / filename
        _write(path, content)
        created.append(path)

    for chart, values in _kubernetes_values(config).items():
        path = root / "kubernetes" / f"{chart}.values.generated.yml"
        _write(
            path,
            "# Generated by owctl; secret values are referenced, never embedded.\n"
            + yaml.safe_dump(values, sort_keys=False),
        )
        created.append(path)

    if config["deployment"]["engine"] == "docker" and config["deployment"]["mode"] == "cluster":
        for node in config["nodes"]:
            node_root = root / "docker" / "nodes" / node["name"]
            for filename, content in _docker_cluster_node_files(config, node).items():
                path = node_root / filename
                _write(path, content)
                created.append(path)

    summary = {
        "name": config["metadata"]["name"],
        "environment": environment,
        "engine": config["deployment"]["engine"],
        "mode": config["deployment"]["mode"],
        "domain": config["network"]["domain"],
        "nodes": [
            {"name": node["name"], "address": node["address"], "roles": node["roles"]}
            for node in config["nodes"]
        ],
        "enabledComponents": [
            name for name, item in config["components"].items() if item["enabled"]
        ],
    }
    summary_path = root / "summary.json"
    _write(summary_path, json.dumps(summary, indent=2) + "\n")
    created.append(summary_path)
    return created
