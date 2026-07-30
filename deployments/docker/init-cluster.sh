#!/usr/bin/env bash
# SPDX-License-Identifier: 0BSD

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_FILE="${CONFIG_FILE:-${REPOSITORY_ROOT}/config/examples/docker-cluster.yml}"
SECRET_FILE="${SECRET_FILE:-${REPOSITORY_ROOT}/secrets/observeweaver.env}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" - \
  "${CONFIG_FILE}" "${SECRET_FILE}" >"${REPOSITORY_ROOT}/.observeweaver-mongo-init.js" <<'PY'
import sys
from pathlib import Path

import yaml

config = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
secrets = {}
for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
    if line and not line.lstrip().startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        secrets[key] = value
members = [
    node for node in config["nodes"] if "data" in node["roles"]
][:3]
port = config["network"]["ports"]["mongodb"]
items = ",\n".join(
    f'    {{ _id: {index}, host: "{node["name"]}:{port}" }}'
    for index, node in enumerate(members)
)
print(
    f'''try {{
  rs.status();
}} catch (error) {{
  rs.initiate({{
    _id: "observeweaver",
    members: [
{items}
    ]
  }});
}}
'''
)
PY

trap 'rm -f "${REPOSITORY_ROOT}/.observeweaver-mongo-init.js"' EXIT
first_node="$(
  PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" - "${CONFIG_FILE}" <<'PY'
import sys
from observeweaver.config import load_config
for node in load_config(sys.argv[1])["nodes"]:
    if "data" in node["roles"]:
        print(node["name"])
        break
PY
)"
mongodb_port="$(
  PYTHONPATH="${REPOSITORY_ROOT}/src" "${PYTHON_BIN}" - "${CONFIG_FILE}" <<'PY'
import sys
from observeweaver.config import load_config
print(load_config(sys.argv[1])["network"]["ports"]["mongodb"])
PY
)"

docker cp \
  "${REPOSITORY_ROOT}/.observeweaver-mongo-init.js" \
  "observeweaver-${first_node}-mongodb-1:/tmp/observeweaver-mongo-init.js"
mongodb_password="$(
  awk -F= '$1 == "MONGODB_ROOT_PASSWORD" {sub(/^[^=]*=/, ""); print; exit}' "${SECRET_FILE}"
)"
printf '%s\n' "${mongodb_password}" | docker exec -i \
  "observeweaver-${first_node}-mongodb-1" \
  mongosh \
  --quiet \
  --port "${mongodb_port}" \
  --username graylog \
  --password \
  --authenticationDatabase admin \
  /tmp/observeweaver-mongo-init.js
unset mongodb_password

printf 'MongoDB replica set initialization submitted from %s.\n' "${first_node}"
