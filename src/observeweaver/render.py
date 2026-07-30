"""Render deployment-specific, non-secret configuration from the canonical YAML."""

from __future__ import annotations

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
    "graylog": "graylog/graylog:7.1.6",
}

DOCKER_IMAGE_LOCKS = {
    "prometheus": (
        "prom/prometheus@sha256:"
        "3c42b892cf723fa54d2f262c37a0e1f80aa8c8ddb1da7b9b0df9455a35a7f893"
    ),
    "alertmanager": (
        "prom/alertmanager@sha256:"
        "9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d"
    ),
    "grafana": (
        "grafana/grafana@sha256:"
        "7cb8c64c4d57a57e734073f3cc94620adb24a0acb929bd80ba9f14017e3a975b"
    ),
    "opentelemetry": (
        "otel/opentelemetry-collector-contrib@sha256:"
        "f2f01157055a9b2aab9df7118e1f1c9abf345e99b23bc7a2bc791db374a7d0f6"
    ),
    "postgresql": (
        "postgres@sha256:"
        "a426e44bac0b759c95894d68e1a0ac03ecc20b619f498a91aae373bf06d8508d"
    ),
    "zabbixServer": (
        "zabbix/zabbix-server-pgsql@sha256:"
        "7b8628474136fae6e1d643278e46ab6d3cd66146fe0a4dbc64a1d22a61ae0c85"
    ),
    "zabbixWeb": (
        "zabbix/zabbix-web-nginx-pgsql@sha256:"
        "4d109f30358363e4483d4aac43eeec80eb4ec605c9d300f4c235475056c5b06e"
    ),
    "mongodb": (
        "mongo@sha256:"
        "5351bff2b5d1563e3fa603a74b9be85ef9323e10aeb0b45cea933a93876e77fd"
    ),
    "opensearch": (
        "opensearchproject/opensearch@sha256:"
        "4ee82ecb35d837a6186c81aaa64c8a5bce71aa956edbd87f1f684ab56af52c44"
    ),
    "graylog": (
        "graylog/graylog@sha256:"
        "b9a4fd841e4c49c148043265f579554a3bdadf8137ff381b686c194ccb9a3365"
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
        )
        if _component(config, name)["enabled"]
    ]
    if _component(config, "graylog")["enabled"]:
        active_profiles.append("mongodb")
    entries = {
        "OBSERVEWEAVER_DOMAIN": config["network"]["domain"],
        "OBSERVEWEAVER_SCHEME": "https"
        if config["tls"]["mode"] != "disabled"
        else "http",
        "OBSERVEWEAVER_BIND_ADDRESS": bind_address,
        "OBSERVEWEAVER_ENDPOINT_ADDRESS": _endpoint_host(bind_address),
        "OBSERVEWEAVER_MODE": config["deployment"]["mode"],
        "PROMETHEUS_VERSION": _component(config, "prometheus")["version"],
        "PROMETHEUS_ENABLED": str(
            _component(config, "prometheus")["enabled"]
        ).lower(),
        "ALERTMANAGER_VERSION": _component(config, "alertmanager")["version"],
        "ALERTMANAGER_ENABLED": str(
            _component(config, "alertmanager")["enabled"]
        ).lower(),
        "GRAFANA_VERSION": _component(config, "grafana")["version"],
        "GRAFANA_ENABLED": str(_component(config, "grafana")["enabled"]).lower(),
        "OTELCOL_VERSION": _component(config, "opentelemetry")["version"],
        "OTELCOL_ENABLED": str(
            _component(config, "opentelemetry")["enabled"]
        ).lower(),
        "ZABBIX_VERSION": _component(config, "zabbix")["version"],
        "ZABBIX_ENABLED": str(_component(config, "zabbix")["enabled"]).lower(),
        "GRAYLOG_VERSION": _component(config, "graylog")["version"],
        "GRAYLOG_ENABLED": str(_component(config, "graylog")["enabled"]).lower(),
        "OPENSEARCH_VERSION": _component(config, "opensearch")["version"],
        "OPENSEARCH_ENABLED": str(
            _component(config, "opensearch")["enabled"]
        ).lower(),
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
        "GRAYLOG_IMAGE": DOCKER_IMAGE_LOCKS["graylog"],
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
        "MONGODB_PORT": ports["mongodb"],
        "PROMETHEUS_RETENTION": f"{config['retention']['metricsDays']}d",
        "GRAYLOG_RETENTION_DAYS": config["retention"]["logsDays"],
        "GRAYLOG_ELASTICSEARCH_REPLICAS": (
            1 if config["deployment"]["mode"] == "cluster" else 0
        ),
        "OPENSEARCH_JAVA_OPTS": _component(config, "opensearch").get(
            "javaOpts", "-Xms2g -Xmx2g"
        ),
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
                    "static_configs": [
                        {"targets": [f"otel-collector:{ports['otelMetrics']}"]}
                    ],
                },
                {
                    "job_name": "otel-exported-metrics",
                    "static_configs": [
                        {
                            "targets": [
                                f"otel-collector:{ports['otelPrometheus']}"
                            ]
                        }
                    ],
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
                {
                    "static_configs": [
                        {"targets": [f"alertmanager:{ports['alertmanager']}"]}
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
        "extensions": {
            "health_check": {"endpoint": f"0.0.0.0:{ports['otelHealth']}"}
        },
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
    prometheus_datasources = [
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
    ] if _component(config, "prometheus")["enabled"] else []
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
    return {
        "prometheus.yml": yaml.safe_dump(prometheus, sort_keys=False),
        "prometheus-rules.yml": yaml.safe_dump(rules, sort_keys=False),
        "alertmanager.yml": yaml.safe_dump(alertmanager, sort_keys=False),
        "otel-collector.yml": yaml.safe_dump(otel, sort_keys=False),
        "grafana-datasources.yml": yaml.safe_dump(datasource, sort_keys=False),
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
            "secret_file": config["security"]["secretFile"],
        }
    }
    return "# Generated by owctl; contains no secret values.\n" + yaml.safe_dump(
        safe_config, sort_keys=False
    )


def _kubernetes_values(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    storage = config["storage"]
    sizes = storage["sizes"]
    ports = config["network"]["ports"]
    domain = config["network"]["domain"]
    ingress_enabled = config["network"]["ingress"]["enabled"]
    ingress_class = config["network"]["ingress"].get("className", "")
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
                    "defaultDatasourceEnabled": _component(
                        config, "prometheus"
                    )["enabled"]
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
            }
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
            }
        },
    }
    if ingress_enabled and config["tls"]["mode"] == "cert-manager":
        issuer = config["tls"]["certManager"]["clusterIssuer"]
        prometheus["grafana"]["ingress"]["annotations"] = {
            "cert-manager.io/cluster-issuer": issuer
        }
        prometheus["grafana"]["ingress"]["tls"] = [
            {
                "secretName": "observeweaver-grafana-tls",
                "hosts": [f"grafana.{domain}"],
            }
        ]
    if (
        _component(config, "grafana")["enabled"]
        and _replicas(config, "grafana") > 1
    ):
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
                "prometheus": {
                    "endpoint": f"0.0.0.0:{ports['otelPrometheus']}"
                },
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
                }
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
                "GRAYLOG_HTTP_BIND_ADDRESS": (
                    f"{ANY_IPV4}:{ports['graylogHttp']}"
                ),
                "GRAYLOG_ELASTICSEARCH_REPLICAS": (
                    "1" if config["deployment"]["mode"] == "cluster" else "0"
                ),
                "GRAYLOG_ROTATION_STRATEGY": "time",
                "GRAYLOG_ELASTICSEARCH_MAX_TIME_PER_INDEX": "1d",
                "GRAYLOG_RETENTION_STRATEGY": "delete",
                "GRAYLOG_ELASTICSEARCH_MAX_NUMBER_OF_INDICES": str(
                    config["retention"]["logsDays"]
                ),
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
                "GRAYLOG_DATANODE_DATANODE_HTTP_PORT": str(
                    ports["graylogDataNode"]
                ),
                "GRAYLOG_DATANODE_OPENSEARCH_HTTP_PORT": str(
                    ports["opensearch"]
                ),
                "GRAYLOG_DATANODE_OPENSEARCH_TRANSPORT_PORT": str(
                    ports["opensearchTransport"]
                ),
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
    if ingress_enabled and config["tls"]["mode"] == "cert-manager":
        issuer = config["tls"]["certManager"]["clusterIssuer"]
        graylog["ingress"]["config"]["tls"] = {
            "clusterIssuer": {"existingName": issuer}
        }
        graylog["ingress"]["web"]["annotations"] = {
            "cert-manager.io/cluster-issuer": issuer
        }
        graylog["ingress"]["web"]["tls"] = [
            {
                "secretName": "observeweaver-graylog-tls",
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
    }


def _docker_cluster_node_files(
    config: dict[str, Any], node: dict[str, Any]
) -> dict[str, str]:
    ports = config["network"]["ports"]
    metrics_nodes = [
        item for item in config["nodes"] if "metrics" in item["roles"]
    ]
    telemetry_nodes = [
        item for item in config["nodes"] if "telemetry" in item["roles"]
    ]
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
    }
    component_nodes = {
        name: nodes[: _replicas(config, name)]
        if _component(config, name)["enabled"]
        else []
        for name, nodes in eligible_nodes.items()
    }
    mongodb_nodes = (
        data_nodes[: 3 if config["deployment"]["mode"] == "cluster" else 1]
        if _component(config, "graylog")["enabled"]
        else []
    )
    active_profiles = [
        profile
        for profile, assigned_nodes in component_nodes.items()
        if node in assigned_nodes
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
        "OBSERVEWEAVER_SCHEME": "https"
        if config["tls"]["mode"] != "disabled"
        else "http",
        "PROMETHEUS_VERSION": _component(config, "prometheus")["version"],
        "PROMETHEUS_ENABLED": str(
            _component(config, "prometheus")["enabled"]
        ).lower(),
        "ALERTMANAGER_VERSION": _component(config, "alertmanager")["version"],
        "ALERTMANAGER_ENABLED": str(
            _component(config, "alertmanager")["enabled"]
        ).lower(),
        "GRAFANA_VERSION": _component(config, "grafana")["version"],
        "GRAFANA_ENABLED": str(_component(config, "grafana")["enabled"]).lower(),
        "OTELCOL_VERSION": _component(config, "opentelemetry")["version"],
        "OTELCOL_ENABLED": str(
            _component(config, "opentelemetry")["enabled"]
        ).lower(),
        "GRAYLOG_VERSION": _component(config, "graylog")["version"],
        "GRAYLOG_ENABLED": str(_component(config, "graylog")["enabled"]).lower(),
        "OPENSEARCH_VERSION": _component(config, "opensearch")["version"],
        "OPENSEARCH_ENABLED": str(
            _component(config, "opensearch")["enabled"]
        ).lower(),
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
        "GRAYLOG_IMAGE": DOCKER_IMAGE_LOCKS["graylog"],
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
        "MONGODB_PORT": ports["mongodb"],
        "PROMETHEUS_RETENTION": f"{config['retention']['metricsDays']}d",
        "GRAYLOG_RETENTION_DAYS": config["retention"]["logsDays"],
        "GRAYLOG_ELASTICSEARCH_REPLICAS": (
            1 if config["deployment"]["mode"] == "cluster" else 0
        ),
        "OPENSEARCH_JAVA_OPTS": _component(config, "opensearch").get(
            "javaOpts", "-Xms2g -Xmx2g"
        ),
        "OPENSEARCH_SEED_HOSTS": ",".join(
            _host_port(item["name"], ports["opensearchTransport"])
            for item in component_nodes["opensearch"]
        ),
        "OPENSEARCH_INITIAL_CLUSTER_MANAGER_NODES": ",".join(
            item["name"] for item in component_nodes["opensearch"]
        ),
        "ALERTMANAGER_PEERS": ",".join(
            f"{item['name']}:{ports['alertmanagerCluster']}"
            for item in component_nodes["alertmanager"]
            if item["name"] != node["name"]
        ),
        "COMPOSE_PROFILES": ",".join(active_profiles),
    }
    if not zabbix_external_database:
        node_env["ZABBIX_DATABASE_HOST"] = (
            zabbix_nodes[0]["address"] if zabbix_nodes else ""
        )
    env_text = "# Generated by owctl; contains no secret values.\n" + "\n".join(
        f"{key}={value}" for key, value in node_env.items()
    ) + "\n"

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
                                _host_port(
                                    item["address"], ports["otelPrometheus"]
                                )
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
        "extensions": {
            "health_check": {"endpoint": f"0.0.0.0:{ports['otelHealth']}"}
        },
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
            "prometheus": {
                "endpoint": f"0.0.0.0:{ports['otelPrometheus']}"
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
    mongo_hosts = ",".join(
        f"{item['name']}:{ports['mongodb']}" for item in mongodb_nodes
    )
    search_hosts = ",".join(
        f"http://{item['name']}:{ports['opensearch']}"
        for item in component_nodes["opensearch"]
    )
    datasource_node = (
        node
        if node in component_nodes["prometheus"]
        else component_nodes["prometheus"][0]
        if component_nodes["prometheus"]
        else None
    )
    prometheus_datasources = [
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
    ] if datasource_node else []
    datasource = {
        "apiVersion": 1,
        "deleteDatasources": [{"name": "Prometheus", "orgId": 1}],
        "datasources": prometheus_datasources,
    }
    extra_hosts = {
        item["name"]: item["address"] for item in config["nodes"]
    }
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
                "graylog",
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
    if mongodb_nodes and node["name"] == mongodb_nodes[0]["name"]:
        override["services"]["mongodb"] = {
            "extra_hosts": extra_hosts,
            "environment": {
                "MONGO_INITDB_ROOT_USERNAME": "graylog",
                "MONGO_INITDB_ROOT_PASSWORD": "${MONGODB_ROOT_PASSWORD}",
                "MONGO_INITDB_DATABASE": "graylog",
            }
        }
    return {
        ".env.generated": env_text,
        "prometheus.yml": yaml.safe_dump(prometheus, sort_keys=False),
        "alertmanager.yml": yaml.safe_dump(alertmanager, sort_keys=False),
        "otel-collector.yml": yaml.safe_dump(otel, sort_keys=False),
        "grafana-datasources.yml": yaml.safe_dump(datasource, sort_keys=False),
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

    if (
        config["deployment"]["engine"] == "docker"
        and config["deployment"]["mode"] == "cluster"
    ):
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
