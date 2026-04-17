#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/blackbird/services/deerflow}"
cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing ${APP_DIR}/.env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source ./.env
if [[ -f .deploy/deploy.env ]]; then
  # shellcheck disable=SC1091
  source ./.deploy/deploy.env
fi
set +a

local_healthcheck_url="${LOCAL_HEALTHCHECK_URL:-http://127.0.0.1:${APP_PORT:-32026}/health}"
public_healthcheck_url="${PRODUCTION_HEALTHCHECK_URL:-https://${APP_DOMAIN:?APP_DOMAIN must be set}/health}"

for _ in $(seq 1 20); do
  if curl -fsS "${local_healthcheck_url}" >/dev/null; then
    break
  fi
  sleep 3
done
curl -fsS "${local_healthcheck_url}" >/dev/null

for _ in $(seq 1 20); do
  if curl -fsS "${public_healthcheck_url}" >/dev/null; then
    break
  fi
  sleep 3
done
curl -fsS "${public_healthcheck_url}" >/dev/null
