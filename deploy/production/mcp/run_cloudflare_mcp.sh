#!/usr/bin/env sh
set -eu

token_file="${CLOUDFLARE_MCP_TOKEN_FILE:-/app/.deploy/cloudflare_mcp_token}"

if [ ! -s "${token_file}" ]; then
  echo "Missing Cloudflare MCP token file: ${token_file}" >&2
  exit 1
fi

CLOUDFLARE_MCP_TOKEN="$(cat "${token_file}")"
export CLOUDFLARE_MCP_TOKEN

exec npx -y mcp-remote https://mcp.cloudflare.com/mcp --header "Authorization: Bearer ${CLOUDFLARE_MCP_TOKEN}"
