"""Configuration loading and semantic validation."""

from __future__ import annotations

import ipaddress
import json
import re
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard

import yaml
from jsonschema import Draft202012Validator

API_VERSION = "observeweaver.io/v1alpha1"
ENGINES = {"raw", "docker", "k3s", "rke2"}
MODES = {"standalone", "cluster"}
PLATFORM_FAMILIES = {"linux", "windows"}
LINUX_DISTRIBUTIONS = {"ubuntu", "rocky", "almalinux", "rhel"}
WINDOWS_DISTRIBUTIONS = {"windows", "windows-server"}
COMPONENTS = {
    "prometheus",
    "alertmanager",
    "grafana",
    "opentelemetry",
    "zabbix",
    "graylog",
    "opensearch",
}
REQUIRED_PORTS = {
    "prometheus",
    "alertmanager",
    "alertmanagerCluster",
    "grafana",
    "otlpGrpc",
    "otlpHttp",
    "otelHealth",
    "otelMetrics",
    "otelPrometheus",
    "zabbixServer",
    "zabbixWeb",
    "graylogHttp",
    "graylogDataNode",
    "graylogBeats",
    "graylogGelfTcp",
    "graylogGelfUdp",
    "graylogSyslogTcp",
    "graylogSyslogUdp",
    "opensearch",
    "opensearchTransport",
    "mongodb",
}
NODE_ROLES = {"control", "metrics", "telemetry", "logs", "data", "ingress"}
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.?$"
)
SAFE_PATH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
NODE_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SIZE_RE = re.compile(r"^[1-9][0-9]*(?:Mi|Gi|Ti)$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
REQUIRED_STORAGE_SIZES = {
    "prometheus",
    "alertmanager",
    "grafana",
    "graylogJournal",
    "opensearch",
    "mongodb",
    "postgresql",
    "zabbixPostgresql",
}
SUPPORTED_PLATFORM_VERSIONS = {
    "ubuntu": {"22.04", "24.04", "26.04"},
    "rocky": {"8", "9", "10"},
    "almalinux": {"8", "9", "10"},
    "rhel": {"8", "9", "10"},
    "windows": {"10", "11"},
    "windows-server": {"2019", "2022", "2025"},
}
TESTED_COMPONENT_VERSIONS = {
    "prometheus": "3.13.1",
    "alertmanager": "0.33.1",
    "grafana": "13.1.1",
    "opentelemetry": "0.157.0",
    "zabbix": "7.0.28",
    "graylog": "7.1.6",
    "opensearch": "2.19.5",
}
TESTED_DEPENDENCY_VERSIONS = {
    "mongodb": "8.0.28",
    "postgresql": "17",
}
SCHEMA_FILENAME = "observeweaver-v1alpha1.schema.json"


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded."""


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Configuration file does not exist: {config_path}")
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError("The configuration root must be a YAML mapping.")
    return parsed


def _get(config: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = config
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _is_ip(value: Any) -> TypeGuard[str]:
    if not isinstance(value, str) or not value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _is_dns_name(value: Any) -> bool:
    if not isinstance(value, str) or not value or not HOSTNAME_RE.fullmatch(value):
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return True
    return False


def _require_mapping(config: dict[str, Any], key: str, result: ValidationResult) -> dict:
    value = config.get(key)
    if not isinstance(value, dict):
        result.errors.append(f"{key}: must be a mapping.")
        return {}
    return value


def _version_tuple(value: str) -> tuple[int, ...]:
    numeric = value.split("-", 1)[0].split("+", 1)[0]
    try:
        return tuple(int(part) for part in numeric.split("."))
    except ValueError:
        return ()


def _schema_path() -> Path | None:
    candidates = (
        Path(__file__).resolve().parents[2] / "schema" / SCHEMA_FILENAME,
        Path(sysconfig.get_path("data"))
        / "share"
        / "observeweaver"
        / "schema"
        / SCHEMA_FILENAME,
    )
    return next((path for path in candidates if path.is_file()), None)


def _schema_validation_errors(config: dict[str, Any]) -> list[str]:
    schema_path = _schema_path()
    if schema_path is None:
        return ["schema: bundled configuration schema could not be located."]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(config), key=lambda error: list(error.path))
    formatted = []
    for error in errors:
        location = ".".join(str(item) for item in error.path) or "<root>"
        formatted.append(f"schema.{location}: {error.message}")
    return formatted


def validate_config(config: dict[str, Any]) -> ValidationResult:
    result = ValidationResult(errors=_schema_validation_errors(config))

    if config.get("apiVersion") != API_VERSION:
        result.errors.append(f"apiVersion: must be {API_VERSION!r}.")
    if config.get("kind") != "ObserveWeaver":
        result.errors.append("kind: must be 'ObserveWeaver'.")

    metadata = _require_mapping(config, "metadata", result)
    if not metadata.get("name"):
        result.errors.append("metadata.name: is required.")
    environment = metadata.get("environment", "production")
    if not isinstance(environment, str) or not SAFE_PATH_NAME_RE.fullmatch(environment):
        result.errors.append(
            "metadata.environment: must be a safe name containing only letters, "
            "numbers, dots, underscores, and hyphens."
        )

    deployment = _require_mapping(config, "deployment", result)
    engine = deployment.get("engine")
    mode = deployment.get("mode")
    if engine not in ENGINES:
        result.errors.append(f"deployment.engine: must be one of {sorted(ENGINES)}.")
    if mode not in MODES:
        result.errors.append(f"deployment.mode: must be one of {sorted(MODES)}.")
    namespace = deployment.get("namespace")
    if not isinstance(namespace, str) or not NODE_NAME_RE.fullmatch(namespace):
        result.errors.append("deployment.namespace: must be a valid DNS label.")

    platform = _require_mapping(config, "platform", result)
    family = platform.get("family")
    distribution = platform.get("distribution")
    execution = platform.get("execution", "native")
    platform_version = str(platform.get("version", ""))
    if family not in PLATFORM_FAMILIES:
        result.errors.append(
            f"platform.family: must be one of {sorted(PLATFORM_FAMILIES)}."
        )
    if family == "linux" and distribution not in LINUX_DISTRIBUTIONS:
        result.errors.append(
            f"platform.distribution: Linux must use one of {sorted(LINUX_DISTRIBUTIONS)}."
        )
    if family == "windows" and distribution not in WINDOWS_DISTRIBUTIONS:
        result.errors.append(
            "platform.distribution: Windows must use 'windows' or 'windows-server'."
        )
    if (
        distribution in SUPPORTED_PLATFORM_VERSIONS
        and platform_version not in SUPPORTED_PLATFORM_VERSIONS[distribution]
    ):
        supported = ", ".join(sorted(SUPPORTED_PLATFORM_VERSIONS[distribution]))
        result.errors.append(
            f"platform.version: {distribution} must use a supported version: {supported}."
        )
    if engine in {"k3s", "rke2"} and family != "linux":
        result.errors.append(
            f"deployment.engine={engine} requires Linux server nodes; Windows may only "
            "be an administration client."
        )
    if family == "windows" and engine == "docker" and execution not in {
        "wsl2",
        "linux-vm",
        "remote-linux",
    }:
        result.errors.append(
            "A full Docker deployment on Windows requires platform.execution to be "
            "wsl2, linux-vm, or remote-linux."
        )
    if (
        engine == "raw"
        and distribution in {"rocky", "almalinux", "rhel"}
        and platform_version == "8"
    ):
        result.errors.append(
            "Native Enterprise Linux 8 is incompatible with the maintained "
            "Ansible Core target runtime; use Docker/K3s/RKE2 or Enterprise "
            "Linux 9 for raw installation."
        )

    nodes = config.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        result.errors.append("nodes: must contain at least one node.")
        nodes = []
    if mode == "standalone" and len(nodes) != 1:
        result.errors.append("nodes: standalone mode requires exactly one node.")
    if mode == "cluster" and len(nodes) < 3:
        result.errors.append("nodes: cluster mode requires at least three nodes.")

    names: set[str] = set()
    addresses: set[str] = set()
    control_count = 0
    for index, node in enumerate(nodes):
        prefix = f"nodes[{index}]"
        if not isinstance(node, dict):
            result.errors.append(f"{prefix}: must be a mapping.")
            continue
        name = node.get("name")
        address = node.get("address")
        roles = node.get("roles")
        if not isinstance(name, str) or not NODE_NAME_RE.fullmatch(name):
            result.errors.append(f"{prefix}.name: must be a valid lowercase DNS label.")
        elif name in names:
            result.errors.append(f"{prefix}.name: duplicate node name {name!r}.")
        else:
            names.add(name)
        if not _is_ip(address):
            result.errors.append(f"{prefix}.address: must be a valid IP address.")
        elif address in addresses:
            result.errors.append(f"{prefix}.address: duplicate address {address!r}.")
        else:
            addresses.add(address)
        if not isinstance(roles, list) or not roles:
            result.errors.append(f"{prefix}.roles: must contain at least one role.")
        else:
            unknown_roles = sorted(set(roles) - NODE_ROLES)
            if unknown_roles:
                result.errors.append(
                    f"{prefix}.roles: unsupported roles: {', '.join(unknown_roles)}."
                )
            if "control" in roles:
                control_count += 1
    if mode == "cluster" and engine in {"k3s", "rke2"}:
        if control_count < 3 or control_count % 2 == 0:
            result.errors.append(
                "nodes: K3s/RKE2 cluster mode requires an odd number of at least three "
                "control-plane/etcd nodes."
            )
    if engine == "raw" or (engine == "docker" and mode == "cluster"):
        role_requirements = {
            "prometheus": "metrics",
            "alertmanager": "metrics",
            "grafana": "metrics",
            "opentelemetry": "telemetry",
            "zabbix": "metrics",
            "graylog": "logs",
            "opensearch": "data",
        }
        for component_name, role in role_requirements.items():
            if not _get(config, f"components.{component_name}.enabled", False):
                continue
            requested = _get(config, f"components.{component_name}.replicas", 1)
            if (
                isinstance(requested, bool)
                or not isinstance(requested, int)
                or requested < 1
            ):
                continue
            available = sum(
                1
                for node in nodes
                if isinstance(node, dict) and role in node.get("roles", [])
            )
            if requested > available:
                result.errors.append(
                    f"components.{component_name}.replicas={requested} exceeds the "
                    f"{available} nodes assigned role {role!r}."
                )

    network = _require_mapping(config, "network", result)
    if not _is_dns_name(network.get("domain")):
        result.errors.append("network.domain: must be a valid DNS name.")
    if not _is_ip(network.get("bindAddress")):
        result.errors.append("network.bindAddress: must be a valid IP address.")
    ingress = network.get("ingress")
    if not isinstance(ingress, dict):
        result.errors.append("network.ingress: must be a mapping.")
    elif not isinstance(ingress.get("enabled"), bool):
        result.errors.append("network.ingress.enabled: must be true or false.")
    vip = network.get("vip")
    if vip not in {None, ""}:
        try:
            ipaddress.ip_address(str(vip))
        except ValueError:
            result.errors.append("network.vip: must be an IP address or null.")
    ports = network.get("ports")
    if not isinstance(ports, dict) or not ports:
        result.errors.append("network.ports: must be a non-empty mapping.")
    else:
        missing_ports = sorted(REQUIRED_PORTS - set(ports))
        if missing_ports:
            result.errors.append(
                f"network.ports: missing required keys: {', '.join(missing_ports)}."
            )
        for name, port in ports.items():
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                result.errors.append(f"network.ports.{name}: must be an integer from 1 to 65535.")
        if engine in {"raw", "docker"}:
            tcp_names = [
                name
                for name in REQUIRED_PORTS
                if name not in {"graylogGelfUdp", "graylogSyslogUdp"}
                and name in ports
            ]
            tcp_by_port: dict[int, list[str]] = {}
            for name in tcp_names:
                if isinstance(ports[name], int):
                    tcp_by_port.setdefault(ports[name], []).append(name)
            for port, names_on_port in sorted(tcp_by_port.items()):
                if len(names_on_port) > 1:
                    result.errors.append(
                        f"network.ports: TCP port {port} is assigned to "
                        f"{', '.join(sorted(names_on_port))}."
                    )
            udp_names = [
                name
                for name in (
                    "alertmanagerCluster",
                    "graylogGelfUdp",
                    "graylogSyslogUdp",
                )
                if name in ports
            ]
            udp_by_port: dict[int, list[str]] = {}
            for name in udp_names:
                if isinstance(ports[name], int):
                    udp_by_port.setdefault(ports[name], []).append(name)
            for port, names_on_port in sorted(udp_by_port.items()):
                if len(names_on_port) > 1:
                    result.errors.append(
                        f"network.ports: UDP port {port} is assigned to "
                        f"{', '.join(sorted(names_on_port))}."
                    )

    components = _require_mapping(config, "components", result)
    for name in sorted(COMPONENTS):
        if not isinstance(components.get(name), dict):
            result.errors.append(f"components.{name}: must be a mapping.")
            continue
        if not isinstance(components[name].get("enabled"), bool):
            result.errors.append(f"components.{name}.enabled: must be true or false.")
        replicas = components[name].get("replicas")
        if (
            isinstance(replicas, bool)
            or not isinstance(replicas, int)
            or replicas < 1
        ):
            result.errors.append(
                f"components.{name}.replicas: must be a positive integer."
            )
        elif mode == "standalone" and replicas != 1:
            result.errors.append(
                f"components.{name}.replicas: standalone mode requires exactly 1."
            )
        version = components[name].get("version")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            result.errors.append(f"components.{name}.version: must be a pinned version.")
        elif version.lower() == "latest":
            result.errors.append(f"components.{name}.version: 'latest' is not reproducible.")
        elif version != TESTED_COMPONENT_VERSIONS[name]:
            result.errors.append(
                f"components.{name}.version: {version!r} is outside the tested "
                f"pinset ({TESTED_COMPONENT_VERSIONS[name]}). Update the artifact "
                "lock and integration tests before changing it."
            )

    if _get(config, "components.graylog.enabled", False):
        if not _get(config, "components.opensearch.enabled", False):
            result.errors.append(
                "components.opensearch.enabled: must be true when Graylog is enabled."
            )
        graylog_version = _version_tuple(
            str(_get(config, "components.graylog.version", ""))
        )
        opensearch_version = _version_tuple(
            str(_get(config, "components.opensearch.version", ""))
        )
        mongodb_version = _version_tuple(
            str(_get(config, "dependencies.mongodb.version", ""))
        )
        if graylog_version[:2] == (7, 1):
            if not opensearch_version or opensearch_version[0] != 2:
                result.errors.append(
                    "Graylog 7.1 requires a compatible OpenSearch 2.x backend; "
                    "OpenSearch 3.x is not supported."
                )
            elif opensearch_version > (2, 19, 5):
                result.errors.append(
                    "Graylog 7.1 supports self-managed OpenSearch only through 2.19.5."
                )
            if (
                not mongodb_version
                or mongodb_version[:2] < (7, 0)
                or mongodb_version[:2] > (8, 0)
            ):
                result.errors.append(
                    "The conservative Graylog 7.1 profile requires MongoDB 7.x or 8.0.x."
                )
    if (
        engine in {"k3s", "rke2"}
        and _get(config, "components.opensearch.enabled", False)
        and not _get(config, "components.graylog.enabled", False)
    ):
        result.errors.append(
            "K3s/RKE2 provides OpenSearch through Graylog Data Node; enable "
            "Graylog or disable this OpenSearch profile."
        )
    if engine in {"k3s", "rke2"} and isinstance(ports, dict):
        fixed_chart_ports = {
            "alertmanagerCluster": 9094,
            "mongodb": 27017,
        }
        for port_name, required_port in fixed_chart_ports.items():
            if ports.get(port_name) != required_port:
                result.errors.append(
                    f"network.ports.{port_name}: the locked Kubernetes charts "
                    f"require {required_port}; this port remains editable for raw "
                    "and Docker deployments."
                )

    if (
        family == "windows"
        and engine == "raw"
        and _get(config, "components.graylog.enabled", False)
    ):
        result.errors.append(
            "Graylog Server has no supported native Windows installation. Set "
            "components.graylog.enabled=false for a native Windows node, or use a Linux "
            "VM/WSL2/remote Linux deployment for the full stack."
        )
    if family == "windows" and engine == "raw" and mode == "cluster":
        result.errors.append(
            "Native Windows supports standalone selected components only; use "
            "Linux nodes for a clustered central stack."
        )

    dependencies = _require_mapping(config, "dependencies", result)
    for dependency_name in ("mongodb", "postgresql", "zabbixPostgresql"):
        dependency = dependencies.get(dependency_name)
        if not isinstance(dependency, dict):
            result.errors.append(
                f"dependencies.{dependency_name}: must be a mapping."
            )
            continue
        dependency_version = dependency.get("version")
        if (
            not isinstance(dependency_version, str)
            or not VERSION_RE.fullmatch(dependency_version)
            or dependency_version.lower() == "latest"
        ):
            result.errors.append(
                f"dependencies.{dependency_name}.version: must be a pinned version."
            )
        expected_dependency = (
            "postgresql" if dependency_name == "zabbixPostgresql" else dependency_name
        )
        expected_version = TESTED_DEPENDENCY_VERSIONS[expected_dependency]
        if dependency_version != expected_version:
            result.errors.append(
                f"dependencies.{dependency_name}.version: {dependency_version!r} "
                "is outside the tested pinset "
                f"({expected_version})."
            )

    mongodb_external = _get(config, "dependencies.mongodb.external", False)
    graylog_enabled = _get(config, "components.graylog.enabled", False)
    if (
        engine == "raw"
        and graylog_enabled
        and (
            (distribution == "ubuntu" and platform_version == "26.04")
            or (
                distribution in {"rocky", "almalinux", "rhel"}
                and platform_version == "10"
            )
        )
        and mongodb_external is not True
    ):
        result.errors.append(
            "Raw Graylog on Ubuntu 26.04 or Enterprise Linux 10 requires "
            "dependencies.mongodb.external=true and MONGODB_URI set to an "
            "operator-managed MongoDB endpoint, because the pinned MongoDB "
            "8.0 package is not supported on those host releases."
        )

    zabbix_enabled = _get(config, "components.zabbix.enabled", False)
    zabbix_replicas = _get(config, "components.zabbix.replicas", 1)
    zabbix_database_external = _get(config, "dependencies.zabbixPostgresql.external", False)
    if (
        zabbix_enabled
        and engine in {"raw", "docker", "k3s", "rke2"}
        and mode == "cluster"
        and isinstance(zabbix_replicas, int)
        and not isinstance(zabbix_replicas, bool)
        and zabbix_replicas > 1
        and zabbix_database_external is not True
    ):
        result.errors.append(
            "Zabbix HA requires dependencies.zabbixPostgresql.external=true and "
            "ZABBIX_DATABASE_HOST set to a resilient external PostgreSQL endpoint "
            "in the secret file."
        )
    if zabbix_enabled and engine == "raw" and zabbix_database_external is not True:
        result.errors.append(
            "Native Zabbix uses an operator-managed PostgreSQL service; set "
            "dependencies.zabbixPostgresql.external=true and provide its endpoint "
            "and credentials through the secret file."
        )

    storage = _require_mapping(config, "storage", result)
    class_name = storage.get("className")
    if mode == "cluster" and engine in {"k3s", "rke2"} and not class_name:
        result.errors.append(
            "storage.className: is required for a persistent K3s/RKE2 cluster deployment."
        )
    if (
        engine in {"k3s", "rke2"}
        and _get(config, "components.graylog.enabled", False)
        and deployment.get("acceptBetaGraylogChart") is not True
    ):
        result.errors.append(
            "deployment.acceptBetaGraylogChart=true is required because the official "
            "Graylog 1.0.0 Helm chart is currently beta."
        )
    sizes = storage.get("sizes")
    if not isinstance(sizes, dict):
        result.errors.append("storage.sizes: must be a mapping.")
    else:
        missing_sizes = sorted(REQUIRED_STORAGE_SIZES - set(sizes))
        if missing_sizes:
            result.errors.append(
                f"storage.sizes: missing required keys: {', '.join(missing_sizes)}."
            )
        for name, size in sizes.items():
            if not isinstance(size, str) or not SIZE_RE.fullmatch(size):
                result.errors.append(
                    f"storage.sizes.{name}: must use Mi, Gi, or Ti notation (for example 50Gi)."
                )

    retention = _require_mapping(config, "retention", result)
    for name, value in retention.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            result.errors.append(f"retention.{name}: must be a positive integer.")

    security = _require_mapping(config, "security", result)
    if environment == "production" and security.get("allowPlaintext", False):
        result.errors.append("security.allowPlaintext: cannot be true in production.")
    secret_file = security.get("secretFile")
    if not isinstance(secret_file, str) or not secret_file:
        result.errors.append("security.secretFile: must reference an external secret file.")

    tls = _require_mapping(config, "tls", result)
    tls_mode = tls.get("mode")
    if tls_mode not in {"provided", "cert-manager", "disabled"}:
        result.errors.append(
            "tls.mode: must be provided, cert-manager, or disabled."
        )
    if environment == "production" and tls_mode == "disabled":
        result.errors.append("tls.mode: cannot be disabled in production.")
    if tls_mode == "cert-manager" and engine not in {"k3s", "rke2"}:
        result.errors.append("tls.mode=cert-manager is only valid for K3s or RKE2.")
    if tls_mode == "provided" and engine in {"k3s", "rke2"}:
        result.errors.append(
            "K3s/RKE2 currently requires tls.mode=cert-manager; provided "
            "certificates are not rendered into the charts."
        )
    if tls_mode == "cert-manager" and not _get(
        config, "tls.certManager.clusterIssuer"
    ):
        result.errors.append(
            "tls.certManager.clusterIssuer: is required for cert-manager mode."
        )
    if tls_mode == "provided":
        for key in ("certificateFile", "privateKeyFile"):
            if not _get(config, f"tls.provided.{key}"):
                result.errors.append(
                    f"tls.provided.{key}: is required for provided certificate mode."
                )
        if not _get(config, "network.ingress.enabled", False):
            result.errors.append(
                "network.ingress.enabled: must be true for externally terminated "
                "provided TLS."
            )
    if environment == "production":
        expected_tls_mode = (
            "cert-manager" if engine in {"k3s", "rke2"} else "provided"
        )
        if tls_mode != expected_tls_mode:
            result.errors.append(
                f"tls.mode: production {engine} deployments require "
                f"{expected_tls_mode!r}."
            )

    if mode == "standalone":
        result.warnings.append(
            "Standalone mode has no service or data-node high availability."
        )
    prometheus_replicas = _get(config, "components.prometheus.replicas", 1)
    if (
        mode == "cluster"
        and isinstance(prometheus_replicas, int)
        and not isinstance(prometheus_replicas, bool)
        and prometheus_replicas > 1
    ):
        result.warnings.append(
            "Replicated Prometheus improves scrape availability but does not provide a "
            "deduplicated global query layer; add Thanos/Mimir when that is required."
        )
    grafana_replicas = _get(config, "components.grafana.replicas", 1)
    if (
        mode == "cluster"
        and _get(config, "components.grafana.enabled", False)
        and isinstance(grafana_replicas, int)
        and not isinstance(grafana_replicas, bool)
        and grafana_replicas > 1
    ):
        if not _get(config, "dependencies.postgresql.external", False):
            result.errors.append(
                "Grafana with multiple replicas requires dependencies.postgresql.external=true "
                "and a shared PostgreSQL connection supplied through the secret file."
            )
    if (
        engine == "docker"
        and mode == "cluster"
        and _get(config, "components.grafana.enabled", False)
        and not _get(config, "dependencies.postgresql.external", False)
    ):
        result.errors.append(
            "Docker cluster Grafana uses an external PostgreSQL database even "
            "with one replica; set dependencies.postgresql.external=true and "
            "supply the connection through the secret file."
        )
    if (
        engine == "docker"
        and mode == "cluster"
        and _get(config, "components.opensearch.enabled", False)
    ):
        result.warnings.append(
            "Docker cluster OpenSearch uses plaintext, unauthenticated east-west "
            "traffic. Restrict the host network and ports 9200/9300 to trusted "
            "data-node addresses, or use raw/K3s/RKE2 for a secured backend."
        )
    if family == "windows":
        result.warnings.append(
            "Review deployments/raw/windows/README.md: full-stack server support requires "
            "a Linux execution layer."
        )
    return result
