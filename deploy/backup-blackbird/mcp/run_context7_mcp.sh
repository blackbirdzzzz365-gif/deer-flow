#!/usr/bin/env sh
set -eu

key_file="${CONTEXT7_API_KEY_FILE:-/app/.deploy/context7_api_key}"

if [ ! -s "${key_file}" ]; then
  echo "Missing Context7 API key file: ${key_file}" >&2
  exit 1
fi

CONTEXT7_API_KEY="$(cat "${key_file}")"
export CONTEXT7_API_KEY

exec npx -y @upstash/context7-mcp --api-key "${CONTEXT7_API_KEY}"
