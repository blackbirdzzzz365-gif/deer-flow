#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/blackbird/services/deerflow}"
DEPLOY_SHA="${DEPLOY_SHA:?DEPLOY_SHA is required}"
BACKEND_IMAGE_REF="${BACKEND_IMAGE_REF:?BACKEND_IMAGE_REF is required}"
FRONTEND_IMAGE_REF="${FRONTEND_IMAGE_REF:?FRONTEND_IMAGE_REF is required}"

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing ${APP_DIR}/.env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source ./.env
set +a

deploy_dir="${APP_DIR}/.deploy"
config_dir="${APP_DIR}/config"
state_file="${deploy_dir}/production-state.env"
deploy_env_file="${deploy_dir}/deploy.env"
secret_file="${deploy_dir}/better-auth-secret"

mkdir -p "${deploy_dir}" "${config_dir}" "${DEER_FLOW_HOME}" "${APP_DIR}/backend/.langgraph_api"

if [[ ! -f "${DEER_FLOW_CONFIG_PATH}" ]]; then
  cp "${APP_DIR}/deploy/production/config.template.yaml" "${DEER_FLOW_CONFIG_PATH}"
fi

if [[ ! -f "${DEER_FLOW_EXTENSIONS_CONFIG_PATH}" ]]; then
  cp "${APP_DIR}/deploy/production/extensions_config.template.json" "${DEER_FLOW_EXTENSIONS_CONFIG_PATH}"
fi

better_auth_secret="${BETTER_AUTH_SECRET:-}"
if [[ -z "${better_auth_secret}" ]]; then
  if [[ -f "${secret_file}" ]]; then
    better_auth_secret="$(cat "${secret_file}")"
  else
    better_auth_secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    printf '%s' "${better_auth_secret}" > "${secret_file}"
    chmod 600 "${secret_file}"
  fi
fi

if [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  printf '%s' "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USERNAME}" --password-stdin
fi

previous_sha=""
previous_backend_image_ref=""
previous_frontend_image_ref=""
if [[ -f "${state_file}" ]]; then
  # shellcheck disable=SC1090
  source "${state_file}"
  previous_sha="${CURRENT_SHA:-${PREVIOUS_SHA:-}}"
  previous_backend_image_ref="${CURRENT_BACKEND_IMAGE_REF:-}"
  previous_frontend_image_ref="${CURRENT_FRONTEND_IMAGE_REF:-}"
fi

cat > "${deploy_env_file}" <<EOF
APP_DIR=${APP_DIR}
BETTER_AUTH_SECRET=${better_auth_secret}
BACKEND_IMAGE_REF=${BACKEND_IMAGE_REF}
FRONTEND_IMAGE_REF=${FRONTEND_IMAGE_REF}
DEPLOY_SHA=${DEPLOY_SHA}
EOF

docker compose --env-file .env --env-file "${deploy_env_file}" -f docker-compose.production.yml pull
docker compose --env-file .env --env-file "${deploy_env_file}" -f docker-compose.production.yml up -d --remove-orphans

APP_DIR="${APP_DIR}" scripts/healthcheck_production.sh

deployed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
cat > "${state_file}" <<EOF
CURRENT_SHA=${DEPLOY_SHA}
CURRENT_BACKEND_IMAGE_REF=${BACKEND_IMAGE_REF}
CURRENT_FRONTEND_IMAGE_REF=${FRONTEND_IMAGE_REF}
PREVIOUS_SHA=${previous_sha}
PREVIOUS_BACKEND_IMAGE_REF=${previous_backend_image_ref}
PREVIOUS_FRONTEND_IMAGE_REF=${previous_frontend_image_ref}
DEPLOYED_AT=${deployed_at}
EOF

docker compose --env-file .env --env-file "${deploy_env_file}" -f docker-compose.production.yml ps
