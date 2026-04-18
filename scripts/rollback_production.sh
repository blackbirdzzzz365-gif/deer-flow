#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/blackbird/services/deerflow}"
COMPOSE_FILES="${COMPOSE_FILES:-docker-compose.production.yml}"
ROLLBACK_SHA="${ROLLBACK_SHA:-${1:-}}"

cd "${APP_DIR}"

if [[ ! -f .env ]]; then
  echo "Missing ${APP_DIR}/.env" >&2
  exit 1
fi

compose_args=()
IFS=',' read -r -a compose_files <<< "${COMPOSE_FILES}"
for compose_file in "${compose_files[@]}"; do
  compose_file="${compose_file//[[:space:]]/}"
  [[ -n "${compose_file}" ]] || continue
  if [[ ! -f "${compose_file}" ]]; then
    echo "Missing compose file: ${APP_DIR}/${compose_file}" >&2
    exit 1
  fi
  compose_args+=(-f "${compose_file}")
done

if [[ ${#compose_args[@]} -eq 0 ]]; then
  echo "No compose files resolved from COMPOSE_FILES=${COMPOSE_FILES}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source ./.env
set +a

deploy_dir="${APP_DIR}/.deploy"
state_file="${deploy_dir}/production-state.env"
deploy_env_file="${deploy_dir}/deploy.env"
secret_file="${deploy_dir}/better-auth-secret"

if [[ ! -f "${state_file}" ]]; then
  echo "Missing production state file: ${state_file}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${state_file}"

target_sha="${ROLLBACK_SHA}"
backend_image_ref=""
frontend_image_ref=""

if [[ -z "${target_sha}" ]]; then
  target_sha="${PREVIOUS_SHA:-}"
  backend_image_ref="${PREVIOUS_BACKEND_IMAGE_REF:-}"
  frontend_image_ref="${PREVIOUS_FRONTEND_IMAGE_REF:-}"
fi

if [[ -z "${target_sha}" ]]; then
  echo "No rollback target available." >&2
  exit 1
fi

if [[ -z "${backend_image_ref}" ]]; then
  backend_image_ref="${IMAGE_REPO_BACKEND:?IMAGE_REPO_BACKEND must be set}:sha-${target_sha}"
fi

if [[ -z "${frontend_image_ref}" ]]; then
  frontend_image_ref="${IMAGE_REPO_FRONTEND:?IMAGE_REPO_FRONTEND must be set}:sha-${target_sha}"
fi

better_auth_secret="${BETTER_AUTH_SECRET:-}"
better_auth_base_url="${BETTER_AUTH_BASE_URL:-}"
if [[ -z "${better_auth_secret}" && -f "${secret_file}" ]]; then
  better_auth_secret="$(cat "${secret_file}")"
fi

if [[ -z "${better_auth_secret}" ]]; then
  echo "Missing BETTER_AUTH_SECRET runtime material." >&2
  exit 1
fi

if [[ -z "${better_auth_base_url}" ]]; then
  better_auth_base_url="https://${APP_DOMAIN:?APP_DOMAIN must be set}"
fi

if [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  printf '%s' "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USERNAME}" --password-stdin
fi

cat > "${deploy_env_file}" <<EOF
APP_DIR=${APP_DIR}
BETTER_AUTH_BASE_URL=${better_auth_base_url}
BETTER_AUTH_SECRET=${better_auth_secret}
BACKEND_IMAGE_REF=${backend_image_ref}
FRONTEND_IMAGE_REF=${frontend_image_ref}
DEPLOY_SHA=${target_sha}
EOF

docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" pull
docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" up -d --remove-orphans

APP_DIR="${APP_DIR}" scripts/healthcheck_production.sh

rolled_back_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
cat > "${state_file}" <<EOF
CURRENT_SHA=${target_sha}
CURRENT_BACKEND_IMAGE_REF=${backend_image_ref}
CURRENT_FRONTEND_IMAGE_REF=${frontend_image_ref}
PREVIOUS_SHA=${CURRENT_SHA:-}
PREVIOUS_BACKEND_IMAGE_REF=${CURRENT_BACKEND_IMAGE_REF:-}
PREVIOUS_FRONTEND_IMAGE_REF=${CURRENT_FRONTEND_IMAGE_REF:-}
ROLLED_BACK_AT=${rolled_back_at}
EOF

docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" ps
