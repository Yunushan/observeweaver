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
