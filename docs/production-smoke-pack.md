# DeerFlow Production Smoke Pack

Use this after a production deploy on `backup-blackbird` to get a repeatable
runtime verdict before doing deeper manual audits.

## Scope

The standard smoke pack has two layers:

1. `scripts/smoke_production.sh`
   - public healthcheck
   - host-local healthcheck
   - deployed SHA and image refs from `production-state.env`
   - homepage marker check
   - `/api/agents` response-shape check
2. optional Playwright browser checks
   - landing page loads on mobile
   - workspace chat route exposes the mobile sidebar trigger
   - workspace agents route exposes the mobile sidebar trigger

The shell script is the required baseline. Playwright is the recommended
browser layer when a deploy touches UI, auth, or navigation.

## Baseline Run

From the repo root:

```bash
scripts/smoke_production.sh
```

Default production values are already wired to:

- `https://deerflow.blackbirdzzzz.art`
- `ssh -p 44518 ubuntu@e1.chiasegpu.vn`
- `/home/ubuntu/services/deerflow/.deploy/production-state.env`

You can override them if production coordinates change:

```bash
PRODUCTION_BASE_URL=https://deerflow.blackbirdzzzz.art \
PRODUCTION_SSH_TARGET=ubuntu@e1.chiasegpu.vn \
PRODUCTION_SSH_PORT=44518 \
scripts/smoke_production.sh
```

## Expected Pass Signals

- public `/health` returns `{"status":"healthy",...}`
- host-local `http://127.0.0.1:32026/health` returns `healthy`
- `production-state.env` contains:
  - `CURRENT_SHA`
  - `CURRENT_BACKEND_IMAGE_REF`
  - `CURRENT_FRONTEND_IMAGE_REF`
  - `DEPLOYED_AT`
- homepage HTML still contains the core product markers:
  - required:
    - `with DeerFlow`
    - `/workspace`
    - `<title>DeerFlow</title>`
  - plus at least one marker from each copy group:
    - `Open Workspace` or `Get Started with 2.0`
    - `structured execution` or `researches, codes, and creates`
- `/api/agents` returns JSON with an `agents` array

## Optional Playwright Browser Layer

When UI or auth changed, run these checks as well. This follows the Codex
Playwright skill and assumes `npx` is available.

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
```

Recommended sequence:

```bash
"$PWCLI" open https://deerflow.blackbirdzzzz.art --headed
"$PWCLI" snapshot
"$PWCLI" fallback-screenshot https://deerflow.blackbirdzzzz.art output/playwright/deerflow-home.png
"$PWCLI" fallback-dom https://deerflow.blackbirdzzzz.art/workspace/chats output/playwright/deerflow-workspace-chats.html
"$PWCLI" fallback-dom https://deerflow.blackbirdzzzz.art/workspace/agents output/playwright/deerflow-workspace-agents.html
```

If you need a true interactive mobile check, reopen the workspace routes in the
CLI, switch to a mobile-sized viewport, snapshot, and confirm the mobile
sidebar trigger is present before signing off the deploy.

## When To Stop And Escalate

Stop and investigate before further rollout if any of these fail:

- public healthcheck fails
- host-local healthcheck fails
- `CURRENT_SHA` does not match the intended deploy SHA
- homepage markers disappear
- `/api/agents` no longer returns an `agents` array
- browser checks lose the mobile sidebar trigger on workspace routes
