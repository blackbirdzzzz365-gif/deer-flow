#!/usr/bin/env bash
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:-blackbirdzzzz365-gif/deer-flow}"
ROLLBACK_SHA="${1:-}"

if [[ -n "${ROLLBACK_SHA}" ]]; then
  gh workflow run rollback-production.yml -R "${GITHUB_REPO}" -f rollback_sha="${ROLLBACK_SHA}"
else
  gh workflow run rollback-production.yml -R "${GITHUB_REPO}"
fi
