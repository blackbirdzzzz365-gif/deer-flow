#!/usr/bin/env sh
set -eu

key_file="${TAVILY_API_KEY_FILE:-/app/.deploy/tavily_api_key}"

if [ ! -s "${key_file}" ]; then
  echo "Missing Tavily API key file: ${key_file}" >&2
  exit 1
fi

TAVILY_API_KEY="$(cat "${key_file}")"
export TAVILY_API_KEY

exec npx -y tavily-mcp@latest
