#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_FILE="${CONFIG_FILE:-${REPOSITORY_ROOT}/config/examples/standalone.yml}"

read_config() {
  PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" - "${CONFIG_FILE}" "$1" <<'PY'
import sys
from observeweaver.config import load_config

value = load_config(sys.argv[1])
for key in sys.argv[2].split("."):
    value = value[key]
print(value)
PY
}

read_secret() {
  "${PYTHON_BIN}" - "$1" "$2" <<'PY'
import sys

path, wanted = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    for raw_line in stream:
        line = raw_line.rstrip("\r\n")
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == wanted:
            print(value)
            raise SystemExit
raise SystemExit(f"ERROR: {wanted} is missing from {path}")
PY
}

cluster_node_address() {
  PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" - \
    "${CONFIG_FILE}" "${NODE_NAME:-}" <<'PY'
import sys
from observeweaver.config import load_config

config = load_config(sys.argv[1])
node_name = sys.argv[2]
for node in config["nodes"]:
    if node["name"] == node_name:
        print(node["address"])
        raise SystemExit
raise SystemExit(f"ERROR: NODE_NAME does not exist in nodes[]: {node_name!r}")
PY
}

endpoint_host() {
  "${PYTHON_BIN}" - "$1" <<'PY'
import ipaddress
import sys

host = sys.argv[1]
try:
    print(f"[{host}]" if ipaddress.ip_address(host).version == 6 else host)
except ValueError:
    print(host)
PY
}

component_is_local() {
  local component="$1"
  PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" - \
    "${CONFIG_FILE}" "${component}" "${NODE_NAME:-}" <<'PY'
import sys
from observeweaver.config import load_config

config = load_config(sys.argv[1])
component = sys.argv[2]
node_name = sys.argv[3]
if config["deployment"]["mode"] == "standalone":
    print("True")
    raise SystemExit
roles = {
    "prometheus": "metrics",
    "alertmanager": "metrics",
    "grafana": "metrics",
    "opentelemetry": "telemetry",
    "zabbix": "metrics",
    "graylog": "logs",
    "opensearch": "data",
    "redis": "data",
}
eligible = [node for node in config["nodes"] if roles[component] in node["roles"]]
replicas = config["components"][component]["replicas"]
print(str(any(node["name"] == node_name for node in eligible[:replicas])))
PY
}

if [[
  "$(read_config deployment.engine)" == "docker" &&
  "$(read_config deployment.mode)" == "cluster"
]]; then
  if [[ -z "${NODE_NAME:-}" ]]; then
    printf 'ERROR: Docker cluster verification requires NODE_NAME.\n' >&2
    exit 2
  fi
  bind_address="$(cluster_node_address)"
else
  bind_address="$(read_config network.bindAddress)"
fi
if [[ "${bind_address}" == "0.0.0.0" || "${bind_address}" == "::" ]]; then
  bind_address="127.0.0.1"
fi
bind_address="$(endpoint_host "${bind_address}")"
platform_family="$(read_config platform.family)"
secret_file="${SECRET_FILE:-$(read_config security.secretFile)}"
if [[ "${secret_file}" != /* ]]; then
  secret_file="${REPOSITORY_ROOT}/${secret_file}"
fi
opensearch_ca_file="${OPENSEARCH_CA_FILE:-/etc/opensearch/observeweaver-root-ca.pem}"

declare -A checks=()
if [[
  "$(read_config components.prometheus.enabled)" == "True" &&
  "$(component_is_local prometheus)" == "True"
]]; then
  checks[prometheus]="http://${bind_address}:$(read_config network.ports.prometheus)/-/ready"
fi
if [[
  "$(read_config components.alertmanager.enabled)" == "True" &&
  "$(component_is_local alertmanager)" == "True"
]]; then
  checks[alertmanager]="http://${bind_address}:$(read_config network.ports.alertmanager)/-/ready"
fi
if [[
  "$(read_config components.grafana.enabled)" == "True" &&
  "$(component_is_local grafana)" == "True"
]]; then
  checks[grafana]="http://${bind_address}:$(read_config network.ports.grafana)/api/health"
fi
if [[
  "$(read_config components.opentelemetry.enabled)" == "True" &&
  "$(component_is_local opentelemetry)" == "True"
]]; then
  checks[otel-collector]="http://${bind_address}:$(read_config network.ports.otelHealth)/"
fi
if [[
  "$(read_config components.zabbix.enabled)" == "True" &&
  "$(component_is_local zabbix)" == "True"
]]; then
  checks[zabbix-web]="http://${bind_address}:$(read_config network.ports.zabbixWeb)/"
fi
if [[
  "$(read_config components.graylog.enabled)" == "True" &&
  "$(component_is_local graylog)" == "True"
]]; then
  checks[graylog]="http://${bind_address}:$(read_config network.ports.graylogHttp)/api/system/lbstatus"
fi
if [[
  "$(read_config deployment.engine)" == "raw" &&
  "$(read_config components.opensearch.enabled)" == "True" &&
  "$(component_is_local opensearch)" == "True"
]]; then
  if [[ "${platform_family}" == "windows" ]]; then
    checks[opensearch]="http://${bind_address}:$(read_config network.ports.opensearch)/_cluster/health"
  else
    checks[opensearch]="https://${bind_address}:$(read_config network.ports.opensearch)/_cluster/health"
  fi
fi

status=0
for component in "${!checks[@]}"; do
  if [[
    "${component}" == "opensearch" &&
    "${platform_family}" == "linux"
  ]]; then
    if [[ ! -r "${opensearch_ca_file}" ]]; then
      printf 'FAIL  opensearch (CA file is not readable: %s)\n' \
        "${opensearch_ca_file}" >&2
      status=1
      continue
    fi
    if [[ ! -r "${secret_file}" ]]; then
      printf 'FAIL  opensearch (secret file is not readable: %s)\n' \
        "${secret_file}" >&2
      status=1
      continue
    fi
    opensearch_password="$(
      read_secret "${secret_file}" OPENSEARCH_INITIAL_ADMIN_PASSWORD
    )"
    if printf 'user = "admin:%s"\n' "${opensearch_password}" |
      curl --fail --silent --show-error --max-time 10 \
        --cacert "${opensearch_ca_file}" --config - \
        "${checks[${component}]}" >/dev/null; then
      printf 'PASS  %s\n' "${component}"
    else
      printf 'FAIL  %s (%s)\n' \
        "${component}" "${checks[${component}]}" >&2
      status=1
    fi
  elif curl --fail --silent --show-error --max-time 10 \
    "${checks[${component}]}" >/dev/null; then
    printf 'PASS  %s\n' "${component}"
  else
    printf 'FAIL  %s (%s)\n' "${component}" "${checks[${component}]}" >&2
    status=1
  fi
done

if [[
  "$(read_config components.zabbix.enabled)" == "True" &&
  "$(component_is_local zabbix)" == "True"
]]; then
  zabbix_host="${bind_address#[}"
  zabbix_host="${zabbix_host%]}"
  zabbix_port="$(read_config network.ports.zabbixServer)"
  if "${PYTHON_BIN}" - "${zabbix_host}" "${zabbix_port}" <<'PY'
import socket
import sys

with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=10):
    pass
PY
  then
    printf 'PASS  zabbix-server\n'
  else
    printf 'FAIL  zabbix-server (%s:%s)\n' \
      "${zabbix_host}" "${zabbix_port}" >&2
    status=1
  fi
fi

if [[
  "$(read_config components.redis.enabled)" == "True" &&
  ( "$(read_config deployment.engine)" == "raw" ||
    ( "$(read_config deployment.engine)" == "docker" &&
      "$(read_config deployment.mode)" == "cluster" ) ) &&
  "$(component_is_local redis)" == "True"
]]; then
  if [[ ! -r "${secret_file}" ]]; then
    printf 'FAIL  redis (secret file is not readable: %s)\n' "${secret_file}" >&2
    exit 1
  fi
  redis_host="${bind_address#[}"
  redis_host="${redis_host%]}"
  REDIS_PASSWORD="$(read_secret "${secret_file}" REDIS_PASSWORD)" \
    "${PYTHON_BIN}" - "${redis_host}" "$(read_config network.ports.redis)" <<'PY'
import os
import socket
import sys

host, raw_port = sys.argv[1:]
password = os.environ["REDIS_PASSWORD"].encode("utf-8")
with socket.create_connection((host, int(raw_port)), timeout=10) as connection:
    connection.sendall(
        b"*2\r\n$4\r\nAUTH\r\n$" + str(len(password)).encode() + b"\r\n" + password + b"\r\n"
        + b"*1\r\n$4\r\nPING\r\n"
    )
    response = connection.recv(128)
if not response.endswith(b"+PONG\r\n"):
    raise SystemExit(f"unexpected Redis response: {response!r}")
PY
  then
    printf 'PASS  redis\n'
  else
    printf 'FAIL  redis (%s:%s)\n' \
      "${redis_host}" "$(read_config network.ports.redis)" >&2
    status=1
  fi
fi
exit "${status}"
