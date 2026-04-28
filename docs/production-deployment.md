# Production Deployment

This is the single canonical referral file for production, deploy, and post-coding release work on DeerFlow.
If an agent needs one file to understand how DeerFlow must be deployed today, use this file.

## Current Production Truth

- Project: `deer-flow`
- GitHub repo: `blackbirdzzzz365-gif/deer-flow`
- Production runtime role: `compute-primary`
- Production SSH: `ssh -p 57116 ubuntu@e1.chiasegpu.vn`
- Production host: `serverblackbird`
- Production app dir: `/home/blackbird/services/deerflow`
- Production env file: `/home/blackbird/services/deerflow/.env`
- Canonical domain: `deerflow.blackbirdzzzz.art`
- Canonical public healthcheck: `https://deerflow.blackbirdzzzz.art/health`
- Local host healthcheck: `http://127.0.0.1:32026/health`
- GitHub runner label: `compute-primary`
- GitHub runner name: `deerflow-compute-primary`
- GitHub Actions vars:
  - `PRODUCTION_APP_DIR=/home/blackbird/services/deerflow`
  - `PRODUCTION_APP_DOMAIN=deerflow.blackbirdzzzz.art`
  - `PRODUCTION_HEALTHCHECK_URL=https://deerflow.blackbirdzzzz.art/health`
  - `PRODUCTION_RUNNER_LABEL=compute-primary`

As of `2026-04-26`, DeerFlow was cut over to the dedicated compute tunnel on `compute-primary`. `linuxvm-primary` and `backup-blackbird-primary` are not the production runner for DeerFlow. Treat any doc or note that says otherwise as stale.

## Deploy Mode

Production deploys are tied to GitHub `main` and GHCR SHA-tagged images.

- Backend image repo: `ghcr.io/blackbirdzzzz365-gif/deer-flow-backend`
- Frontend image repo: `ghcr.io/blackbirdzzzz365-gif/deer-flow-frontend`
- Primary deploy workflow: `.github/workflows/deploy-production.yml`
- Rollback workflow: `.github/workflows/rollback-production.yml`
- Build workflow: `Build Production Images`
- Quality gate: `CI`
- Runtime architecture: `linux/amd64` on the current `compute-primary` host (`x86_64`)

Do not treat local source on the operator machine or on the host as the deploy source of truth. The deploy source of truth is:

1. code on `main`
2. GHCR images tagged with that exact SHA
3. `Deploy Production` GitHub workflow

The image build must continue publishing both `linux/amd64` and `linux/arm64`; current production uses `linux/amd64`, and replacement compute capacity may differ.

## Server Env And Templates

The production host `.env` follows the compute-primary layout. `scripts/deploy_production.sh` defaults to `deploy/production` and `docker-compose.production.yml`, so those values only need to be overridden if the deploy topology changes.

Core values:

```env
APP_DIR=/home/blackbird/services/deerflow
APP_PORT=32026
APP_DOMAIN=deerflow.blackbirdzzzz.art
PRODUCTION_HEALTHCHECK_URL=https://deerflow.blackbirdzzzz.art/health
LOCAL_HEALTHCHECK_URL=http://127.0.0.1:32026/health
HOST_HOME=/home/blackbird
DEER_FLOW_HOME=/home/blackbird/services/deerflow/runtime
DEER_FLOW_CONFIG_PATH=/home/blackbird/services/deerflow/config/config.yaml
DEER_FLOW_EXTENSIONS_CONFIG_PATH=/home/blackbird/services/deerflow/config/extensions_config.json
DEER_FLOW_DOCKER_SOCKET=/var/run/docker.sock
IMAGE_REPO_BACKEND=ghcr.io/blackbirdzzzz365-gif/deer-flow-backend
IMAGE_REPO_FRONTEND=ghcr.io/blackbirdzzzz365-gif/deer-flow-frontend
GATEWAY_WORKERS=4
LANGGRAPH_JOBS_PER_WORKER=10
LANGGRAPH_ALLOW_BLOCKING=1
DEPLOY_TEMPLATE_DIR=deploy/production
COMPOSE_FILES=docker-compose.production.yml
REQUIRE_PUBLIC_HEALTHCHECK=1
OPENCLAW_SHARED_ENV_FILE=/home/blackbird/.openclaw/.env
NINEROUTER_API_KEY=...
```

Tracked templates and assets that production depends on:

- `deploy/production/app.env.example`
- `deploy/production/config.template.yaml`
- `deploy/production/extensions_config.template.json`
- `deploy/production/mcp/`
- `scripts/deploy_production.sh`
- `scripts/rollback_production.sh`
- `scripts/healthcheck_production.sh`

## Correct Deploy Flow After Coding

1. Push or merge the target commit to `main`.
2. Wait for `CI` to pass for that exact SHA.
3. Wait for `Build Production Images` to pass for that exact SHA.
4. Trigger `Deploy Production`.
5. Verify:
   - `https://deerflow.blackbirdzzzz.art/health`
   - `ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird curl -fsS http://127.0.0.1:32026/health'`
   - `ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird sed -n "1,20p" /home/blackbird/services/deerflow/.deploy/production-state.env'`
   - `ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird /home/blackbird/bin/prod-audit'`
6. If deploy must be undone, use `Roll Back Production`.

After those three checks pass, run the standard smoke pack:

```bash
scripts/smoke_production.sh
```

Typical operator commands:

```bash
gh run list --repo blackbirdzzzz365-gif/deer-flow --limit 10
gh workflow run "Deploy Production" --repo blackbirdzzzz365-gif/deer-flow --ref main
gh run watch <deploy-run-id> --repo blackbirdzzzz365-gif/deer-flow --exit-status
curl -fsS https://deerflow.blackbirdzzzz.art/health
ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird curl -fsS http://127.0.0.1:32026/health'
ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird sed -n "1,20p" /home/blackbird/services/deerflow/.deploy/production-state.env'
ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird /home/blackbird/bin/prod-audit'
```

If you want one guarded command that waits for `CI` and `Build Production Images`
for the same `main` SHA before dispatching `Deploy Production`, use:

```bash
scripts/trigger_production_deploy.sh
```

That helper also watches the deploy run and performs the canonical public/local/state-file
verification unless `SKIP_VERIFY=1` is set.

## What The Deploy Script Now Does

`scripts/deploy_production.sh` is no longer tied to a single compose file or a single template directory.

It now:

1. reads `DEPLOY_TEMPLATE_DIR` from host `.env`
2. reads `COMPOSE_FILES` from host `.env`
3. hydrates file-backed secrets under `.deploy/`
4. copies MCP wrappers from `DEPLOY_TEMPLATE_DIR/mcp/` into `.deploy/`
5. writes `.deploy/deploy.env`
6. runs:
   - `docker compose ... pull`
   - `docker compose ... up -d --remove-orphans`
   - `docker compose ... restart nginx`
7. runs `scripts/healthcheck_production.sh`
8. records the result in `.deploy/production-state.env`

The `nginx` restart is intentional and required. Without it, `nginx:alpine` can keep a stale upstream IP for `gateway` after backend containers are recreated, which causes `/health` to fail with `502` even though the new gateway container is healthy.

## Critical Rules

- Do not use `ssh -p 44518 ubuntu@e1.chiasegpu.vn` as the current production path.
- Keep `PRODUCTION_RUNNER_LABEL=compute-primary`.
- Keep `PRODUCTION_APP_DIR=/home/blackbird/services/deerflow`.
- Do not trigger `Deploy Production` before `Build Production Images` succeeds for the same SHA.
- Do not change self-hosted production workflows or variables back to `linuxvm-primary`.
- Keep production templates under `deploy/production/` tracked in the repo. GitHub deploy uses `rsync --delete`, so anything not tracked in the repo can be deleted on the next deploy.
- Do not remove the `nginx` restart from `scripts/deploy_production.sh` unless the upstream routing model changes and is revalidated.
- Keep `deerflow.blackbirdzzzz.art` as the canonical public URL.
- Keep production mounted to `/home/blackbird/.codex`, `/home/blackbird/.claude`, and `/home/blackbird/.openclaw/.env`.

## Rollback

Use GitHub Actions first:

```bash
gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow
gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow -f rollback_sha=<sha>
```

Or directly on the host if necessary:

```bash
ssh -p 57116 ubuntu@e1.chiasegpu.vn '
  cd /home/blackbird/services/deerflow &&
  scripts/rollback_production.sh
'
```

## Smoke Pack Reference

For the standard post-deploy runtime/API/browser pack, read:

- `docs/production-smoke-pack.md`
