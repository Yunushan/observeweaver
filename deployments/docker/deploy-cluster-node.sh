#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NODE_NAME="${NODE_NAME:-}"
ENVIRONMENT="${ENVIRONMENT:-production}"
SECRET_FILE="${SECRET_FILE:-${REPOSITORY_ROOT}/secrets/observeweaver.env}"

if [[ -z "${NODE_NAME}" ]]; then
  printf 'ERROR: set NODE_NAME to one node name from the canonical config.\n' >&2
  exit 2
fi

node_root="${REPOSITORY_ROOT}/build/${ENVIRONMENT}/docker/nodes/${NODE_NAME}"
if [[ ! -f "${node_root}/.env.generated" ]]; then
  printf 'ERROR: rendered node bundle not found: %s\n' "${node_root}" >&2
  exit 2
fi
if [[ ! -f "${SECRET_FILE}" ]]; then
  printf 'ERROR: secret file not found: %s\n' "${SECRET_FILE}" >&2
  exit 2
fi

export NODE_CONFIG_DIR="${node_root}"
docker compose \
  --project-name "observeweaver-${NODE_NAME}" \
  --env-file "${node_root}/.env.generated" \
  --env-file "${SECRET_FILE}" \
  -f "${REPOSITORY_ROOT}/deployments/docker/compose.cluster-node.yml" \
  -f "${node_root}/compose.override.generated.yml" \
  config --quiet
docker compose \
  --project-name "observeweaver-${NODE_NAME}" \
  --env-file "${node_root}/.env.generated" \
  --env-file "${SECRET_FILE}" \
  -f "${REPOSITORY_ROOT}/deployments/docker/compose.cluster-node.yml" \
  -f "${node_root}/compose.override.generated.yml" \
  up --detach --remove-orphans
