#!/usr/bin/env bash
set -euo pipefail

PRODUCTION_BASE_URL="${PRODUCTION_BASE_URL:-https://deerflow.blackbirdzzzz.art}"
PUBLIC_HEALTHCHECK_URL="${PUBLIC_HEALTHCHECK_URL:-${PRODUCTION_BASE_URL%/}/health}"
AGENTS_API_URL="${AGENTS_API_URL:-${PRODUCTION_BASE_URL%/}/api/agents}"
PRODUCTION_SSH_TARGET="${PRODUCTION_SSH_TARGET:-ubuntu@e1.chiasegpu.vn}"
PRODUCTION_SSH_PORT="${PRODUCTION_SSH_PORT:-57116}"
PRODUCTION_LOCAL_HEALTHCHECK_URL="${PRODUCTION_LOCAL_HEALTHCHECK_URL:-http://127.0.0.1:32026/health}"
PRODUCTION_STATE_FILE="${PRODUCTION_STATE_FILE:-/home/blackbird/services/deerflow/.deploy/production-state.env}"
PRODUCTION_AUDIT_COMMAND="${PRODUCTION_AUDIT_COMMAND:-/home/blackbird/bin/prod-audit}"
RUN_PRODUCTION_AUDIT="${RUN_PRODUCTION_AUDIT:-1}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-20}"

section() {
  echo
  echo "== $1 =="
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

public_health_file="${tmp_dir}/public-health.json"
host_snapshot_file="${tmp_dir}/host-snapshot.txt"
homepage_file="${tmp_dir}/homepage.html"
agents_file="${tmp_dir}/agents.json"

section "Public health"
curl --max-time "${REQUEST_TIMEOUT_SECONDS}" -fsS "${PUBLIC_HEALTHCHECK_URL}" > "${public_health_file}"
cat "${public_health_file}"
echo
python3 - "${public_health_file}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
if payload.get("status") != "healthy":
    raise SystemExit(f"Unexpected public health payload: {payload}")
print(f"Verified public status={payload['status']} service={payload.get('service', 'unknown')}")
PY

section "Host-local health and production state"
ssh -p "${PRODUCTION_SSH_PORT}" "${PRODUCTION_SSH_TARGET}" \
  "sudo -u blackbird curl --max-time ${REQUEST_TIMEOUT_SECONDS} -fsS '${PRODUCTION_LOCAL_HEALTHCHECK_URL}' && printf '\n---\n' && sudo -u blackbird sed -n '1,20p' '${PRODUCTION_STATE_FILE}'" \
  > "${host_snapshot_file}"
cat "${host_snapshot_file}"
echo
python3 - "${host_snapshot_file}" <<'PY'
import json
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text()
health_raw, _, state_raw = raw.partition("\n---\n")
payload = json.loads(health_raw)
if payload.get("status") != "healthy":
    raise SystemExit(f"Unexpected host-local health payload: {payload}")
state = {}
for line in state_raw.splitlines():
    if not line or "=" not in line:
        continue
    key, value = line.split("=", 1)
    state[key] = value
required = {"CURRENT_SHA", "CURRENT_BACKEND_IMAGE_REF", "CURRENT_FRONTEND_IMAGE_REF", "DEPLOYED_AT"}
missing = sorted(required - state.keys())
if missing:
    raise SystemExit(f"Missing state keys: {', '.join(missing)}")
print(f"Verified host-local status={payload['status']} current_sha={state['CURRENT_SHA']}")
PY

section "Homepage content"
curl --max-time "${REQUEST_TIMEOUT_SECONDS}" -fsS "${PRODUCTION_BASE_URL}" > "${homepage_file}"
python3 - "${homepage_file}" <<'PY'
import sys
from pathlib import Path

html = Path(sys.argv[1]).read_text()
required_markers = [
    "<title>DeerFlow</title>",
    "with DeerFlow",
    "/workspace",
]
alternate_groups = [
    ["Open Workspace", "Get Started with 2.0"],
    ["structured execution", "researches, codes, and creates"],
]

missing = [marker for marker in required_markers if marker not in html]
if missing:
    raise SystemExit(f"Homepage missing required markers: {missing}")

failed_groups = []
for group in alternate_groups:
    if not any(marker in html for marker in group):
        failed_groups.append(group)

if failed_groups:
    raise SystemExit(f"Homepage missing at least one marker from each group: {failed_groups}")

print("Verified homepage required markers:", ", ".join(required_markers))
for index, group in enumerate(alternate_groups, start=1):
    matched = [marker for marker in group if marker in html]
    print(f"Verified homepage alternate group {index}: {matched[0]}")
PY

section "Agents API"
curl --max-time "${REQUEST_TIMEOUT_SECONDS}" -fsS "${AGENTS_API_URL}" > "${agents_file}"
cat "${agents_file}"
echo
python3 - "${agents_file}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
agents = payload.get("agents")
if not isinstance(agents, list):
    raise SystemExit(f"Expected 'agents' to be a list, got: {type(agents).__name__}")
print(f"Verified agents API shape: {len(agents)} agent(s)")
PY

if [[ "${RUN_PRODUCTION_AUDIT}" == "1" ]]; then
  section "Compute production audit"
  ssh -p "${PRODUCTION_SSH_PORT}" "${PRODUCTION_SSH_TARGET}" \
    "sudo -u blackbird '${PRODUCTION_AUDIT_COMMAND}'"
fi

section "Summary"
echo "Production smoke pack passed."
echo "Public URL: ${PRODUCTION_BASE_URL}"
echo "Health URL: ${PUBLIC_HEALTHCHECK_URL}"
