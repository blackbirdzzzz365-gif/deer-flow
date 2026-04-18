#!/usr/bin/env sh
set -eu

key_file="${XAI_API_KEY_FILE:-/app/.deploy/xai_api_key}"

if [ -z "${XAI_API_KEY:-}" ] && [ -s "${key_file}" ]; then
  XAI_API_KEY="$(cat "${key_file}")"
  export XAI_API_KEY
fi

if [ -z "${XAI_API_KEY:-}" ]; then
  echo "Missing xAI API key for x_search MCP. Set XAI_API_KEY or provide ${key_file}." >&2
  exit 1
fi

exec sh -lc 'cd /app/backend && uv run --no-sync python /app/.deploy/x_search_mcp.py'
