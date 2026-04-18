#!/usr/bin/env sh
set -eu

key_file="${FIRECRAWL_API_KEY_FILE:-/app/.deploy/firecrawl_api_key}"
url_file="${FIRECRAWL_API_URL_FILE:-/app/.deploy/firecrawl_api_url}"

if [ ! -s "${key_file}" ]; then
  echo "Missing Firecrawl API key file: ${key_file}" >&2
  exit 1
fi

FIRECRAWL_API_KEY="$(cat "${key_file}")"
export FIRECRAWL_API_KEY

if [ -s "${url_file}" ]; then
  FIRECRAWL_API_URL="$(cat "${url_file}")"
  export FIRECRAWL_API_URL
fi

exec npx -y firecrawl-mcp
