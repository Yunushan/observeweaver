#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_FILE="${CONFIG_FILE:-${REPOSITORY_ROOT}/config/examples/cluster.yml}"
GENERATED_VALUES_DIR="${GENERATED_VALUES_DIR:-${REPOSITORY_ROOT}/build/production/kubernetes}"
CHART_CACHE="${CHART_CACHE:-${REPOSITORY_ROOT}/.observeweaver/charts}"

KUBE_PROMETHEUS_CHART_VERSION="87.21.0"
KUBE_PROMETHEUS_CHART_SHA256="05eae98df0ff6c21877a26a4400780e4bbff248bc3b88694ef8d08b273ed6815"
OTEL_CHART_VERSION="0.165.0"
OTEL_CHART_SHA256="b592ea064d9b906930cac2d22b88eeb1bc82f12d5ed07fd20792de2c051ca3c5"
GRAYLOG_CHART_VERSION="1.0.0"
GRAYLOG_CHART_SHA256="06e18864ca7a81809ad23cd081a73b5306ea9f80f78ea3cc71e2abeb64dcf1a4"
MONGODB_OPERATOR_CHART_VERSION="1.6.1"
MONGODB_OPERATOR_CHART_SHA256="4d9d167c5c7f41d559a948f18a24cee64c96530db098b07e39f59825cc12b6fd"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$1" >&2
    exit 2
  fi
}

config_value() {
  local expression="$1"
  PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" - "${CONFIG_FILE}" "${expression}" <<'PY'
import sys
from observeweaver.config import load_config

value = load_config(sys.argv[1])
for key in sys.argv[2].split("."):
    value = value[key]
print(str(value).lower() if isinstance(value, bool) else value)
PY
}

download_chart() {
  local name="$1"
  local url="$2"
  local checksum="$3"
  local destination="${CHART_CACHE}/${name}.tgz"
  mkdir -p "${CHART_CACHE}"
  if [[ ! -f "${destination}" ]]; then
    curl --fail --silent --show-error --location "${url}" --output "${destination}"
  fi
  printf '%s  %s\n' "${checksum}" "${destination}" | sha256sum --check --status
  printf '%s' "${destination}"
}

check_kubernetes_version() {
  local minimum="1.32"
  local current
  current="$(
    kubectl version -o json | "${PYTHON_BIN}" -c \
      'import json,sys; v=json.load(sys.stdin)["serverVersion"]; print("{}.{}".format(v["major"], v["minor"].rstrip("+")))'
  )"
  "${PYTHON_BIN}" - "${current}" "${minimum}" <<'PY'
import sys

current = tuple(int(item) for item in sys.argv[1].split(".")[:2])
minimum = tuple(int(item) for item in sys.argv[2].split(".")[:2])
if current < minimum:
    raise SystemExit(
        f"ERROR: Graylog chart requires Kubernetes {sys.argv[2]}+, found {sys.argv[1]}."
    )
PY
}

create_grafana_secret() {
  local namespace="$1"
  local secret_name="$2"
  local secret_path="$3"
  kubectl -n "${namespace}" create secret generic "${secret_name}" \
    --from-env-file="${secret_path}" \
    --dry-run=client \
    -o yaml | kubectl apply -f -
}

make_graylog_secret_values() {
  local secret_path="$1"
  local destination="$2"
  "${PYTHON_BIN}" - "${secret_path}" "${destination}" <<'PY'
import os
import sys
from pathlib import Path

import yaml

values = {}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not raw or raw.lstrip().startswith("#") or "=" not in raw:
        continue
    key, value = raw.split("=", 1)
    values[key] = value

password = values.get("GRAYLOG_INITIAL_ADMIN_PASSWORD")
if not password:
    raise SystemExit("ERROR: GRAYLOG_INITIAL_ADMIN_PASSWORD is missing from the secret file.")

target = Path(sys.argv[2])
target.write_text(
    yaml.safe_dump({"graylog": {"config": {"rootPassword": password}}}, sort_keys=False),
    encoding="utf-8",
)
os.chmod(target, 0o600)
PY
}

require_command curl
require_command helm
require_command kubectl
require_command sha256sum
require_command "${PYTHON_BIN}"

namespace="$(config_value deployment.namespace)"
secret_name="$(config_value security.kubernetesSecretName)"
secret_path="$(config_value security.secretFile)"
if [[ "${secret_path}" != /* ]]; then
  secret_path="${REPOSITORY_ROOT}/${secret_path}"
fi
if [[ ! -f "${secret_path}" ]]; then
  printf 'ERROR: secret file not found: %s\n' "${secret_path}" >&2
  exit 2
fi

check_kubernetes_version
kubectl get namespace "${namespace}" >/dev/null 2>&1 || kubectl create namespace "${namespace}"

if [[ "$(config_value tls.mode)" == "cert-manager" ]]; then
  issuer="$(config_value tls.certManager.clusterIssuer)"
  if ! kubectl get clusterissuer "${issuer}" >/dev/null 2>&1; then
    printf 'ERROR: configured ClusterIssuer does not exist: %s\n' "${issuer}" >&2
    exit 2
  fi
fi

create_grafana_secret "${namespace}" "${secret_name}" "${secret_path}"

kube_prometheus_chart="$(
  download_chart \
    "kube-prometheus-stack-${KUBE_PROMETHEUS_CHART_VERSION}" \
    "https://github.com/prometheus-community/helm-charts/releases/download/kube-prometheus-stack-${KUBE_PROMETHEUS_CHART_VERSION}/kube-prometheus-stack-${KUBE_PROMETHEUS_CHART_VERSION}.tgz" \
    "${KUBE_PROMETHEUS_CHART_SHA256}"
)"
otel_chart="$(
  download_chart \
    "opentelemetry-collector-${OTEL_CHART_VERSION}" \
    "https://github.com/open-telemetry/opentelemetry-helm-charts/releases/download/opentelemetry-collector-${OTEL_CHART_VERSION}/opentelemetry-collector-${OTEL_CHART_VERSION}.tgz" \
    "${OTEL_CHART_SHA256}"
)"
graylog_chart="$(
  download_chart \
    "graylog-${GRAYLOG_CHART_VERSION}" \
    "https://github.com/Graylog2/graylog-helm/releases/download/graylog-${GRAYLOG_CHART_VERSION}/graylog-${GRAYLOG_CHART_VERSION}.tgz" \
    "${GRAYLOG_CHART_SHA256}"
)"
mongodb_operator_chart="$(
  download_chart \
    "mongodb-kubernetes-${MONGODB_OPERATOR_CHART_VERSION}" \
    "https://github.com/mongodb/helm-charts/releases/download/mongodb-kubernetes-${MONGODB_OPERATOR_CHART_VERSION}/mongodb-kubernetes-${MONGODB_OPERATOR_CHART_VERSION}.tgz" \
    "${MONGODB_OPERATOR_CHART_SHA256}"
)"

if [[
  "$(config_value components.prometheus.enabled)" == "true" ||
  "$(config_value components.alertmanager.enabled)" == "true" ||
  "$(config_value components.grafana.enabled)" == "true"
]]; then
  helm upgrade --install observeweaver-monitoring "${kube_prometheus_chart}" \
    --namespace "${namespace}" \
    --values "${GENERATED_VALUES_DIR}/kube-prometheus-stack.values.generated.yml" \
    --atomic \
    --timeout 20m
fi

if [[ "$(config_value components.opentelemetry.enabled)" == "true" ]]; then
  helm upgrade --install observeweaver-otel "${otel_chart}" \
    --namespace "${namespace}" \
    --values "${GENERATED_VALUES_DIR}/opentelemetry-collector.values.generated.yml" \
    --atomic \
    --timeout 10m
fi

if [[ "$(config_value components.graylog.enabled)" == "true" ]]; then
  helm upgrade --install mongodb-kubernetes-operator "${mongodb_operator_chart}" \
    --namespace mongodb-operator \
    --create-namespace \
    --set 'operator.watchNamespace=*' \
    --atomic \
    --timeout 10m

  temporary_values="$(mktemp)"
  trap 'rm -f "${temporary_values}"' EXIT
  make_graylog_secret_values "${secret_path}" "${temporary_values}"
  helm upgrade --install observeweaver-graylog "${graylog_chart}" \
    --namespace "${namespace}" \
    --values "${GENERATED_VALUES_DIR}/graylog.values.generated.yml" \
    --values "${temporary_values}" \
    --atomic \
    --timeout 30m
fi

kubectl -n "${namespace}" get pods
printf 'ObserveWeaver Kubernetes deployment completed in namespace %s.\n' "${namespace}"
