#!/usr/bin/env bash
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:-blackbirdzzzz365-gif/deer-flow}"

gh workflow run build-image.yml -R "${GITHUB_REPO}"
gh workflow run deploy-production.yml -R "${GITHUB_REPO}"
