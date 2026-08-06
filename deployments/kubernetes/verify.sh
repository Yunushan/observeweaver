#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD

set -euo pipefail

NAMESPACE="${NAMESPACE:-observeweaver}"

kubectl -n "${NAMESPACE}" wait \
  --for=condition=Ready \
  pod \
  --all \
  --timeout=15m

kubectl -n "${NAMESPACE}" get prometheus,alertmanager 2>/dev/null || true
kubectl -n "${NAMESPACE}" get statefulset,deployment,daemonset

# The Elastic bootstrap Job is the gate that creates the Kibana system and
# least-privilege Logstash credentials. A ready pod alone is not sufficient:
# Kibana/Logstash can be running while that credential bootstrap is still
# pending or has failed.
if kubectl -n "${NAMESPACE}" get job/observeweaver-elastic-bootstrap >/dev/null 2>&1; then
  kubectl -n "${NAMESPACE}" wait \
    --for=condition=complete \
    job/observeweaver-elastic-bootstrap \
    --timeout=15m
fi

if kubectl -n "${NAMESPACE}" get statefulset/observeweaver-kafka >/dev/null 2>&1; then
  kubectl -n "${NAMESPACE}" rollout status statefulset/observeweaver-kafka --timeout=15m
fi

not_ready="$(
  kubectl -n "${NAMESPACE}" get pods \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[*].ready}{"\n"}{end}' |
    awk '$0 ~ /false/ {print}'
)"
if [[ -n "${not_ready}" ]]; then
  printf 'ERROR: containers are not ready:\n%s\n' "${not_ready}" >&2
  exit 1
fi

printf 'All ObserveWeaver pods report ready in namespace %s.\n' "${NAMESPACE}"
