#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/home/blackbird/services/deerflow}"
COMPOSE_FILES="${COMPOSE_FILES:-docker-compose.production.yml}"
DEPLOY_TEMPLATE_DIR="${DEPLOY_TEMPLATE_DIR:-deploy/production}"
DEPLOY_SHA="${DEPLOY_SHA:?DEPLOY_SHA is required}"
BACKEND_IMAGE_REF="${BACKEND_IMAGE_REF:?BACKEND_IMAGE_REF is required}"
FRONTEND_IMAGE_REF="${FRONTEND_IMAGE_REF:?FRONTEND_IMAGE_REF is required}"

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

if [[ -z "${NINEROUTER_API_KEY:-}" ]]; then
  echo "Missing NINEROUTER_API_KEY in ${APP_DIR}/.env" >&2
  exit 1
fi

for required_var in OPENHANDS_LLM_MODEL OPENHANDS_LLM_API_KEY OPENHANDS_LLM_BASE_URL OPENHANDS_LLM_CUSTOM_LLM_PROVIDER FEYNMAN_MODEL; do
  if [[ -z "${!required_var:-}" ]]; then
    echo "Missing ${required_var} in ${APP_DIR}/.env; required by OpenHands/Feynman production config" >&2
    exit 1
  fi
done

deploy_dir="${APP_DIR}/.deploy"
config_dir="${APP_DIR}/config"
state_file="${deploy_dir}/production-state.env"
deploy_env_file="${deploy_dir}/deploy.env"
secret_file="${deploy_dir}/better-auth-secret"
xai_secret_file="${deploy_dir}/xai_api_key"
context7_secret_file="${deploy_dir}/context7_api_key"
tavily_secret_file="${deploy_dir}/tavily_api_key"
firecrawl_secret_file="${deploy_dir}/firecrawl_api_key"
firecrawl_url_file="${deploy_dir}/firecrawl_api_url"
cloudflare_secret_file="${deploy_dir}/cloudflare_mcp_token"
shared_openclaw_env_file="${OPENCLAW_SHARED_ENV_FILE:-${HOST_HOME:-/home/blackbird}/.openclaw/.env}"
cloudflare_runtime_loader="${CLOUDFLARE_RUNTIME_LOADER:-${HOST_HOME:-/home/blackbird}/.config/blackbird-deploy/load_runtime.sh}"
default_template_dir="${APP_DIR}/deploy/production"
template_dir="${APP_DIR}/${DEPLOY_TEMPLATE_DIR}"
config_template_path="${template_dir}/config.template.yaml"
extensions_template_path="${template_dir}/extensions_config.template.json"
seed_agents_dir="${template_dir}/agents"
mcp_source_dir="${template_dir}/mcp"
github_mcp_wrapper_source="${APP_DIR}/scripts/run_github_mcp.sh"

read_env_value_from_file() {
  local env_file="${1}"
  local key_csv="${2}"
  python3 - "${env_file}" "${key_csv}" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
keys = {key.strip() for key in sys.argv[2].split(",") if key.strip()}

if not env_path.exists():
    raise SystemExit(0)

for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if key in keys and value:
        print(value, end="")
        break
PY
}

write_secret_file() {
  local destination="${1}"
  local value="${2:-}"
  if [[ -z "${value}" ]]; then
    return 0
  fi

  printf '%s' "${value}" > "${destination}"
  chmod 600 "${destination}"
}

ensure_delegated_runtime_config() {
  local config_path="${1}"
  local template_path="${2}"

  python3 scripts/migrate_delegated_runtime_config.py "${config_path}" "${template_path}"
}

if [[ ! -f "${config_template_path}" ]]; then
  config_template_path="${default_template_dir}/config.template.yaml"
fi

if [[ ! -f "${extensions_template_path}" ]]; then
  extensions_template_path="${default_template_dir}/extensions_config.template.json"
fi

if [[ ! -d "${seed_agents_dir}" ]]; then
  seed_agents_dir="${default_template_dir}/agents"
fi

if [[ ! -d "${mcp_source_dir}" ]]; then
  mcp_source_dir="${default_template_dir}/mcp"
fi

mkdir -p \
  "${deploy_dir}" \
  "${config_dir}" \
  "${DEER_FLOW_HOME}" \
  "${DEER_FLOW_HOME}/openhands-home" \
  "${DEER_FLOW_HOME}/feynman-home" \
  "${APP_DIR}/backend/.langgraph_api"

if [[ ! -f "${DEER_FLOW_CONFIG_PATH}" ]]; then
  cp "${config_template_path}" "${DEER_FLOW_CONFIG_PATH}"
fi
ensure_delegated_runtime_config "${DEER_FLOW_CONFIG_PATH}" "${config_template_path}"

if [[ ! -f "${DEER_FLOW_EXTENSIONS_CONFIG_PATH}" ]]; then
  cp "${extensions_template_path}" "${DEER_FLOW_EXTENSIONS_CONFIG_PATH}"
fi

if [[ -d "${seed_agents_dir}" ]]; then
  mkdir -p "${DEER_FLOW_HOME}/agents"
  for seed_agent_dir in "${seed_agents_dir}"/*; do
    [[ -d "${seed_agent_dir}" ]] || continue
    target_agent_dir="${DEER_FLOW_HOME}/agents/$(basename "${seed_agent_dir}")"
    if [[ ! -d "${target_agent_dir}" ]]; then
      mkdir -p "${target_agent_dir}"
      cp -R "${seed_agent_dir}/." "${target_agent_dir}/"
    elif [[ -f "${seed_agent_dir}/config.yaml" ]]; then
      cp "${seed_agent_dir}/config.yaml" "${target_agent_dir}/config.yaml"
    fi
  done
fi

if [[ -d "${mcp_source_dir}" ]]; then
  shopt -s nullglob
  for mcp_asset in "${mcp_source_dir}"/*.py "${mcp_source_dir}"/*.sh; do
    [[ -f "${mcp_asset}" ]] || continue
    cp "${mcp_asset}" "${deploy_dir}/$(basename "${mcp_asset}")"
    chmod 755 "${deploy_dir}/$(basename "${mcp_asset}")"
  done
  shopt -u nullglob
fi

if [[ -f "${github_mcp_wrapper_source}" ]]; then
  cp "${github_mcp_wrapper_source}" "${deploy_dir}/run_github_mcp.sh"
  chmod 755 "${deploy_dir}/run_github_mcp.sh"
fi

xai_api_key="${XAI_API_KEY:-}"
if [[ -z "${xai_api_key}" && -f "${shared_openclaw_env_file}" ]]; then
  xai_api_key="$(read_env_value_from_file "${shared_openclaw_env_file}" "XAI_API_KEY,OPENCLAW_READER_XAI_API_KEY")"
fi

context7_api_key="${CONTEXT7_API_KEY:-}"
tavily_api_key="${TAVILY_API_KEY:-}"
firecrawl_api_key="${FIRECRAWL_API_KEY:-}"
firecrawl_api_url="${FIRECRAWL_API_URL:-}"
cloudflare_api_token="${CLOUDFLARE_MCP_TOKEN:-${CF_API_TOKEN:-}}"
if [[ -z "${cloudflare_api_token}" && -f "${cloudflare_runtime_loader}" ]]; then
  cloudflare_api_token="$(
    CLOUDFLARE_RUNTIME_LOADER="${cloudflare_runtime_loader}" bash -lc '
      source "${CLOUDFLARE_RUNTIME_LOADER}" >/dev/null 2>&1 || exit 0
      printf %s "${CF_API_TOKEN:-}"
    '
  )"
fi

write_secret_file "${xai_secret_file}" "${xai_api_key}"
write_secret_file "${context7_secret_file}" "${context7_api_key}"
write_secret_file "${tavily_secret_file}" "${tavily_api_key}"
write_secret_file "${firecrawl_secret_file}" "${firecrawl_api_key}"
write_secret_file "${firecrawl_url_file}" "${firecrawl_api_url}"
write_secret_file "${cloudflare_secret_file}" "${cloudflare_api_token}"

better_auth_secret="${BETTER_AUTH_SECRET:-}"
better_auth_base_url="${BETTER_AUTH_BASE_URL:-}"
if [[ -z "${better_auth_secret}" ]]; then
  if [[ -f "${secret_file}" ]]; then
    better_auth_secret="$(cat "${secret_file}")"
  else
    better_auth_secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    printf '%s' "${better_auth_secret}" > "${secret_file}"
    chmod 600 "${secret_file}"
  fi
fi

if [[ -z "${better_auth_base_url}" ]]; then
  better_auth_base_url="https://${APP_DOMAIN:?APP_DOMAIN must be set}"
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
BETTER_AUTH_BASE_URL=${better_auth_base_url}
BETTER_AUTH_SECRET=${better_auth_secret}
BACKEND_IMAGE_REF=${BACKEND_IMAGE_REF}
FRONTEND_IMAGE_REF=${FRONTEND_IMAGE_REF}
DEPLOY_SHA=${DEPLOY_SHA}
XAI_BASE_URL=${XAI_BASE_URL:-}
XAI_X_SEARCH_MODEL=${XAI_X_SEARCH_MODEL:-}
XAI_X_SEARCH_MAX_TURNS=${XAI_X_SEARCH_MAX_TURNS:-}
XAI_X_SEARCH_TIMEOUT_SECONDS=${XAI_X_SEARCH_TIMEOUT_SECONDS:-}
XAI_X_SEARCH_INLINE_CITATIONS=${XAI_X_SEARCH_INLINE_CITATIONS:-}
EOF

docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" pull
docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" up -d --remove-orphans

docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" exec -T langgraph sh -lc 'openhands acp --help >/dev/null && test -w /root/.openhands'
docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" exec -T langgraph sh -lc 'feynman --help >/dev/null && test -w /root/.feynman'

# nginx resolves Docker service names at startup, so it must restart after
# backend/frontend containers are recreated to pick up the new gateway IP.
docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" restart nginx

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

docker compose --env-file .env --env-file "${deploy_env_file}" "${compose_args[@]}" ps
