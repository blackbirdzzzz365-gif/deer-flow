#!/usr/bin/env sh
set -eu

token_file="${GITHUB_MCP_TOKEN_FILE:-/app/.deploy/github_mcp_token}"

if [ ! -s "${token_file}" ]; then
  echo "Missing GitHub MCP token file: ${token_file}" >&2
  exit 1
fi

GITHUB_PERSONAL_ACCESS_TOKEN="$(cat "${token_file}")"
export GITHUB_PERSONAL_ACCESS_TOKEN

exec docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server
