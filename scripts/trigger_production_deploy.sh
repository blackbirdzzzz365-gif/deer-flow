#!/usr/bin/env bash
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:-blackbirdzzzz365-gif/deer-flow}"
TARGET_REF="${TARGET_REF:-main}"
TARGET_SHA="${TARGET_SHA:-}"
CI_WORKFLOW="${CI_WORKFLOW:-CI}"
BUILD_WORKFLOW="${BUILD_WORKFLOW:-Build Production Images}"
DEPLOY_WORKFLOW="${DEPLOY_WORKFLOW:-Deploy Production}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-3600}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-15}"
DEPLOY_DISCOVERY_TIMEOUT_SECONDS="${DEPLOY_DISCOVERY_TIMEOUT_SECONDS:-180}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"
PRODUCTION_HEALTHCHECK_URL="${PRODUCTION_HEALTHCHECK_URL:-https://deerflow.blackbirdzzzz.art/health}"
PRODUCTION_SSH_TARGET="${PRODUCTION_SSH_TARGET:-ubuntu@e1.chiasegpu.vn}"
PRODUCTION_SSH_PORT="${PRODUCTION_SSH_PORT:-57116}"
PRODUCTION_LOCAL_HEALTHCHECK_URL="${PRODUCTION_LOCAL_HEALTHCHECK_URL:-http://127.0.0.1:32026/health}"
PRODUCTION_STATE_FILE="${PRODUCTION_STATE_FILE:-/home/blackbird/services/deerflow/.deploy/production-state.env}"
PRODUCTION_AUDIT_COMMAND="${PRODUCTION_AUDIT_COMMAND:-/home/blackbird/bin/prod-audit}"

resolve_target_sha() {
  if [[ -n "${TARGET_SHA}" ]]; then
    printf '%s\n' "${TARGET_SHA}"
    return 0
  fi

  gh api "repos/${GITHUB_REPO}/commits/${TARGET_REF}" --jq '.sha'
}

latest_run_for_sha() {
  local workflow_name="${1}"
  local target_sha="${2}"
  local output

  output="$(gh run list \
    --repo "${GITHUB_REPO}" \
    --workflow "${workflow_name}" \
    --branch "${TARGET_REF}" \
    --limit 50 \
    --json databaseId,headSha,status,conclusion,createdAt,url)"

  python3 -c '
import json
import sys

target_sha = sys.argv[1]
runs = json.loads(sys.stdin.read())

matches = [run for run in runs if run.get("headSha") == target_sha]
if not matches:
    raise SystemExit(1)

matches.sort(key=lambda run: run.get("createdAt", ""), reverse=True)
run = matches[0]
print(f"{run['\''databaseId'\'']}\t{run['\''status'\'']}\t{run.get('\''conclusion'\'') or '\'''\''}\t{run.get('\''url'\'') or '\'''\''}")
' "${target_sha}" <<<"${output}"
}

wait_for_success() {
  local workflow_name="${1}"
  local target_sha="${2}"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    local run_metadata
    if run_metadata="$(latest_run_for_sha "${workflow_name}" "${target_sha}" 2>/dev/null)"; then
      local run_id status conclusion run_url
      IFS=$'\t' read -r run_id status conclusion run_url <<<"${run_metadata}"
      echo "[${workflow_name}] run=${run_id} status=${status} conclusion=${conclusion:-pending} url=${run_url}"

      if [[ "${status}" == "completed" ]]; then
        if [[ "${conclusion}" == "success" ]]; then
          return 0
        fi

        echo "${workflow_name} failed for ${target_sha}. Inspect ${run_url}" >&2
        return 1
      fi
    else
      echo "[${workflow_name}] waiting for a run on ${target_sha}"
    fi

    sleep "${POLL_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for ${workflow_name} to succeed on ${target_sha}" >&2
  return 1
}

discover_deploy_run() {
  local target_sha="${1}"
  local deadline=$((SECONDS + DEPLOY_DISCOVERY_TIMEOUT_SECONDS))

  while (( SECONDS < deadline )); do
    local run_metadata
    if run_metadata="$(latest_run_for_sha "${DEPLOY_WORKFLOW}" "${target_sha}" 2>/dev/null)"; then
      local run_id
      IFS=$'\t' read -r run_id _ <<<"${run_metadata}"
      printf '%s\n' "${run_id}"
      return 0
    fi

    sleep 5
  done

  return 1
}

verify_production() {
  if [[ "${SKIP_VERIFY}" == "1" ]]; then
    echo "Skipping post-deploy verification because SKIP_VERIFY=1"
    return 0
  fi

  echo "Verifying public healthcheck: ${PRODUCTION_HEALTHCHECK_URL}"
  curl -fsS "${PRODUCTION_HEALTHCHECK_URL}"
  echo
  echo "Verifying host-local healthcheck and state file on ${PRODUCTION_SSH_TARGET}"
  ssh -p "${PRODUCTION_SSH_PORT}" "${PRODUCTION_SSH_TARGET}" \
    "sudo -u blackbird curl -fsS '${PRODUCTION_LOCAL_HEALTHCHECK_URL}' && echo '---' && sudo -u blackbird sed -n '1,20p' '${PRODUCTION_STATE_FILE}' && echo '---' && sudo -u blackbird '${PRODUCTION_AUDIT_COMMAND}'"
}

target_sha="$(resolve_target_sha)"
echo "Target ref: ${TARGET_REF}"
echo "Target SHA: ${target_sha}"

wait_for_success "${CI_WORKFLOW}" "${target_sha}"
wait_for_success "${BUILD_WORKFLOW}" "${target_sha}"

echo "Dispatching ${DEPLOY_WORKFLOW} for ${TARGET_REF} (${target_sha})"
gh workflow run "${DEPLOY_WORKFLOW}" --repo "${GITHUB_REPO}" --ref "${TARGET_REF}"

deploy_run_id="$(discover_deploy_run "${target_sha}")" || {
  echo "Failed to discover a ${DEPLOY_WORKFLOW} run for ${target_sha} after dispatch." >&2
  exit 1
}

echo "Watching deploy run ${deploy_run_id}"
gh run watch "${deploy_run_id}" --repo "${GITHUB_REPO}" --exit-status

verify_production
