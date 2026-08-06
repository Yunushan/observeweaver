#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_FILE="${CONFIG_FILE:-${REPOSITORY_ROOT}/config/examples/standalone.yml}"
OUTPUT_ROOT="${OUTPUT_ROOT:-${REPOSITORY_ROOT}/build}"

usage() {
  printf '%s\n' \
    "Usage: scripts/observeweaver.sh <command> [options]" \
    "" \
    "Commands:" \
    "  validate              Validate CONFIG_FILE." \
    "  render                Render deployment files into OUTPUT_ROOT." \
    "  secrets               Generate the configured secret file." \
    "  deploy --yes          Deploy using deployment.engine." \
    "  verify                Run endpoint health checks." \
    "" \
    "Environment:" \
    "  CONFIG_FILE           Canonical YAML configuration." \
    "  OUTPUT_ROOT           Generated output directory." \
    "  PYTHON_BIN            Python 3.10+ executable."
}

owctl() {
  PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" -m observeweaver.cli "$@"
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

generated_root() {
  printf '%s/%s' "${OUTPUT_ROOT}" "$(config_value metadata.environment)"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$1" >&2
    exit 2
  fi
}

secret_file_path() {
  local secret_path
  secret_path="$(config_value security.secretFile)"
  if [[ "${secret_path}" != /* ]]; then
    secret_path="${REPOSITORY_ROOT}/${secret_path}"
  fi
  printf '%s' "${secret_path}"
}

require_secret_value() {
  local key="$1"
  local secret_path="$2"
  if ! awk -F= -v key="${key}" \
    '$1 == key && length(substr($0, index($0, "=") + 1)) > 0 { found = 1 } END { exit !found }' \
    "${secret_path}"; then
    printf 'ERROR: %s must have a non-empty value in %s.\n' \
      "${key}" "${secret_path}" >&2
    exit 2
  fi
}

preflight_secrets() {
  local engine grafana_enabled grafana_replicas mode secret_path zabbix_enabled
  local elasticsearch_enabled kibana_enabled logstash_enabled
  local zabbix_external_database zabbix_replicas
  secret_path="$(secret_file_path)"
  if [[ ! -f "${secret_path}" ]]; then
    printf 'ERROR: secret file not found: %s. Run the secrets command first.\n' \
      "${secret_path}" >&2
    exit 2
  fi
  engine="$(config_value deployment.engine)"
  mode="$(config_value deployment.mode)"
  grafana_enabled="$(config_value components.grafana.enabled)"
  grafana_replicas="$(config_value components.grafana.replicas)"
  zabbix_enabled="$(config_value components.zabbix.enabled)"
  zabbix_replicas="$(config_value components.zabbix.replicas)"
  zabbix_external_database="$(config_value dependencies.zabbixPostgresql.external)"
  elasticsearch_enabled="$(config_value components.elasticsearch.enabled)"
  kibana_enabled="$(config_value components.kibana.enabled)"
  logstash_enabled="$(config_value components.logstash.enabled)"
  if [[ "${grafana_enabled}" == "true" ]] && {
    (( grafana_replicas > 1 )) || [[
      "${engine}" == "docker" &&
      "${mode}" == "cluster"
    ]]
  }; then
    require_secret_value GRAFANA_DATABASE_HOST "${secret_path}"
    require_secret_value GRAFANA_DATABASE_NAME "${secret_path}"
    require_secret_value GRAFANA_DATABASE_USER "${secret_path}"
    require_secret_value POSTGRES_PASSWORD "${secret_path}"
  fi
  if [[ "${zabbix_enabled}" == "true" && "${zabbix_external_database}" == "true" ]] && {
    [[ "${engine}" == "raw" ]] ||
    [[ "${mode}" == "cluster" ]] && (( zabbix_replicas > 1 ))
  }; then
    require_secret_value ZABBIX_DATABASE_HOST "${secret_path}"
    require_secret_value ZABBIX_DATABASE_PORT "${secret_path}"
    require_secret_value ZABBIX_DATABASE_USER "${secret_path}"
    require_secret_value ZABBIX_DATABASE_PASSWORD "${secret_path}"
    require_secret_value ZABBIX_DATABASE_NAME "${secret_path}"
  fi
  if [[ "${elasticsearch_enabled}" == "true" || "${kibana_enabled}" == "true" || "${logstash_enabled}" == "true" ]]; then
    require_secret_value ELASTICSEARCH_PASSWORD "${secret_path}"
  fi
  if [[ "${kibana_enabled}" == "true" ]]; then
    require_secret_value KIBANA_SYSTEM_PASSWORD "${secret_path}"
    require_secret_value KIBANA_ENCRYPTION_KEY "${secret_path}"
    require_secret_value KIBANA_REPORTING_ENCRYPTION_KEY "${secret_path}"
    require_secret_value KIBANA_SECURITY_ENCRYPTION_KEY "${secret_path}"
  fi
  if [[ "${logstash_enabled}" == "true" ]]; then
    require_secret_value LOGSTASH_WRITER_PASSWORD "${secret_path}"
  fi
}

validate() {
  owctl validate --config "${CONFIG_FILE}"
}

render() {
  owctl render --config "${CONFIG_FILE}" --output "${OUTPUT_ROOT}"
}

generate_secrets() {
  local secret_path
  secret_path="$(config_value security.secretFile)"
  if [[ "${secret_path}" != /* ]]; then
    secret_path="${REPOSITORY_ROOT}/${secret_path}"
  fi
  owctl secrets --output "${secret_path}"
}

deploy_docker() {
  require_command docker
  local root secret_path
  if [[ "$(config_value deployment.mode)" == "cluster" ]]; then
    if [[ -z "${NODE_NAME:-}" ]]; then
      printf 'ERROR: Docker cluster mode requires NODE_NAME for this host.\n' >&2
      exit 2
    fi
    ENVIRONMENT="$(config_value metadata.environment)" \
      NODE_NAME="${NODE_NAME}" \
      SECRET_FILE="$(
        secret_path="$(config_value security.secretFile)"
        if [[ "${secret_path}" != /* ]]; then
          secret_path="${REPOSITORY_ROOT}/${secret_path}"
        fi
        printf '%s' "${secret_path}"
      )" \
      "${REPOSITORY_ROOT}/deployments/docker/deploy-cluster-node.sh"
    return
  fi
  root="$(generated_root)"
  secret_path="$(config_value security.secretFile)"
  if [[ "${secret_path}" != /* ]]; then
    secret_path="${REPOSITORY_ROOT}/${secret_path}"
  fi
  if [[ ! -f "${secret_path}" ]]; then
    printf 'ERROR: secret file not found: %s. Run the secrets command first.\n' "${secret_path}" >&2
    exit 2
  fi
  export DOCKER_CONFIG_DIR="${root}/docker/configs"
  docker compose \
    --project-directory "${REPOSITORY_ROOT}/deployments/docker" \
    --env-file "${root}/docker/.env.generated" \
    --env-file "${secret_path}" \
    -f "${REPOSITORY_ROOT}/deployments/docker/compose.yml" \
    config --quiet
  docker compose \
    --project-directory "${REPOSITORY_ROOT}/deployments/docker" \
    --env-file "${root}/docker/.env.generated" \
    --env-file "${secret_path}" \
    -f "${REPOSITORY_ROOT}/deployments/docker/compose.yml" \
    up --detach --remove-orphans
}

deploy_raw() {
  local root secret_path
  if [[ "$(config_value platform.family)" == "windows" ]]; then
    printf '%s\n' \
      'ERROR: Native Windows deployment uses PowerShell, not Linux Ansible.' \
      'Run deployments/raw/windows/Install-ObserveWeaver.ps1 as documented.' >&2
    exit 2
  fi
  require_command ansible-playbook
  root="$(generated_root)"
  secret_path="$(config_value security.secretFile)"
  if [[ "${secret_path}" != /* ]]; then
    secret_path="${REPOSITORY_ROOT}/${secret_path}"
  fi
  if [[ ! -f "${secret_path}" ]]; then
    printf 'ERROR: secret file not found: %s. Run the secrets command first.\n' "${secret_path}" >&2
    exit 2
  fi
  ANSIBLE_CONFIG="${REPOSITORY_ROOT}/deployments/raw/ansible/ansible.cfg" \
    ansible-playbook \
    -i "${root}/ansible/inventory.generated.ini" \
    "${REPOSITORY_ROOT}/deployments/raw/ansible/playbooks/site.yml" \
    --extra-vars "@${root}/ansible/group_vars.generated.yml" \
    --extra-vars "observeweaver_secret_file=${secret_path}"
}

deploy_kubernetes() {
  local root
  root="$(generated_root)"
  GENERATED_VALUES_DIR="${root}/kubernetes" \
    CONFIG_FILE="${CONFIG_FILE}" \
    "${REPOSITORY_ROOT}/deployments/kubernetes/install.sh"
}

deploy() {
  local engine
  validate
  render
  preflight_secrets
  engine="$(config_value deployment.engine)"
  case "${engine}" in
    docker) deploy_docker ;;
    raw) deploy_raw ;;
    k3s | rke2) deploy_kubernetes ;;
    *)
      printf 'ERROR: unsupported engine: %s\n' "${engine}" >&2
      exit 2
      ;;
  esac
}

verify() {
  local engine root
  engine="$(config_value deployment.engine)"
  root="$(generated_root)"
  case "${engine}" in
    k3s | rke2)
      NAMESPACE="$(config_value deployment.namespace)" \
        "${REPOSITORY_ROOT}/deployments/kubernetes/verify.sh"
      ;;
    raw)
      if [[ "$(config_value platform.family)" == "windows" ]]; then
        CONFIG_FILE="${CONFIG_FILE}" "${REPOSITORY_ROOT}/scripts/verify.sh"
        return
      fi
      require_command ansible-playbook
      local secret_path
      secret_path="$(secret_file_path)"
      ANSIBLE_CONFIG="${REPOSITORY_ROOT}/deployments/raw/ansible/ansible.cfg" \
        ansible-playbook \
        -i "${root}/ansible/inventory.generated.ini" \
        "${REPOSITORY_ROOT}/deployments/raw/ansible/playbooks/verify.yml" \
        --extra-vars "@${root}/ansible/group_vars.generated.yml" \
        --extra-vars "observeweaver_secret_file=${secret_path}"
      ;;
    docker)
      if [[
        "$(config_value deployment.mode)" == "cluster" &&
        -z "${NODE_NAME:-}"
      ]]; then
        printf 'ERROR: Docker cluster verification requires NODE_NAME.\n' >&2
        exit 2
      fi
      CONFIG_FILE="${CONFIG_FILE}" "${REPOSITORY_ROOT}/scripts/verify.sh"
      ;;
    *)
      printf 'ERROR: unsupported engine: %s\n' "${engine}" >&2
      exit 2
      ;;
  esac
}

command_name="${1:-}"
shift || true
case "${command_name}" in
  validate) validate ;;
  render) render ;;
  secrets) generate_secrets ;;
  deploy)
    if [[ "${1:-}" != "--yes" ]]; then
      printf 'ERROR: deployment changes the target systems. Re-run with: deploy --yes\n' >&2
      exit 2
    fi
    deploy
    ;;
  verify)
    verify
    ;;
  help | --help | -h | "") usage ;;
  *)
    printf 'ERROR: unknown command: %s\n' "${command_name}" >&2
    usage >&2
    exit 2
    ;;
esac
