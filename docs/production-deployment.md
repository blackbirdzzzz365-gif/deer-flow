# Production Deployment

## Current Production Truth

- Project: `deer-flow`
- GitHub repo: `blackbirdzzzz365-gif/deer-flow`
- Production runtime host: `backup-blackbird`
- Production SSH: `ssh -p 44518 ubuntu@e1.chiasegpu.vn`
- Production app dir: `/home/ubuntu/services/deerflow`
- Production env file: `/home/ubuntu/services/deerflow/.env`
- Canonical domain: `deerflow.blackbirdzzzz.art`
- Canonical public healthcheck: `https://deerflow.blackbirdzzzz.art/health`
- Local host healthcheck: `http://127.0.0.1:32026/health`
- GitHub runner label: `backup-blackbird-primary`
- GitHub Actions vars:
  - `PRODUCTION_APP_DIR=/home/ubuntu/services/deerflow`
  - `PRODUCTION_APP_DOMAIN=deerflow.blackbirdzzzz.art`
  - `PRODUCTION_HEALTHCHECK_URL=https://deerflow.blackbirdzzzz.art/health`
  - `PRODUCTION_RUNNER_LABEL=backup-blackbird-primary`

Production no longer runs on `linuxvm`. `linuxvm` was drained on `2026-04-18` to free disk.

## Deploy Mode

Production deploys are tied to GitHub `main` and GHCR SHA-tagged images.

- Backend image repo: `ghcr.io/blackbirdzzzz365-gif/deer-flow-backend`
- Frontend image repo: `ghcr.io/blackbirdzzzz365-gif/deer-flow-frontend`
- Primary deploy workflow: `.github/workflows/deploy-production.yml`
- Rollback workflow: `.github/workflows/rollback-production.yml`
- Build workflow: `Build Production Images`
- Quality gate: `CI`

Do not treat local source on the operator machine or on the host as the deploy source of truth. The deploy source of truth is:

1. code on `main`
2. GHCR images tagged with that exact SHA
3. `Deploy Production` GitHub workflow

## Server Env And Templates

The production host `.env` must follow the backup-blackbird variant, not the old linuxvm layout.

Core values:

```env
APP_DIR=/home/ubuntu/services/deerflow
APP_PORT=32026
APP_DOMAIN=deerflow.blackbirdzzzz.art
PRODUCTION_HEALTHCHECK_URL=https://deerflow.blackbirdzzzz.art/health
LOCAL_HEALTHCHECK_URL=http://127.0.0.1:32026/health
HOST_HOME=/home/ubuntu
DEER_FLOW_HOME=/home/ubuntu/services/deerflow/runtime
DEER_FLOW_CONFIG_PATH=/home/ubuntu/services/deerflow/config/config.yaml
DEER_FLOW_EXTENSIONS_CONFIG_PATH=/home/ubuntu/services/deerflow/config/extensions_config.json
DEER_FLOW_DOCKER_SOCKET=/var/run/docker.sock
IMAGE_REPO_BACKEND=ghcr.io/blackbirdzzzz365-gif/deer-flow-backend
IMAGE_REPO_FRONTEND=ghcr.io/blackbirdzzzz365-gif/deer-flow-frontend
GATEWAY_WORKERS=2
LANGGRAPH_JOBS_PER_WORKER=4
LANGGRAPH_ALLOW_BLOCKING=1
DEPLOY_TEMPLATE_DIR=deploy/backup-blackbird
COMPOSE_FILES=docker-compose.production.yml,deploy/backup-blackbird/docker-compose.override.yml
REQUIRE_PUBLIC_HEALTHCHECK=1
OPENCLAW_SHARED_ENV_FILE=/home/ubuntu/.openclaw/.env
NINEROUTER_API_KEY=...
```

Tracked templates and assets that production depends on:

- `deploy/backup-blackbird/app.env.example`
- `deploy/backup-blackbird/config.template.yaml`
- `deploy/backup-blackbird/extensions_config.template.json`
- `deploy/backup-blackbird/docker-compose.override.yml`
- `deploy/backup-blackbird/mcp/`
- `deploy/backup-blackbird/agents/`
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
   - `http://127.0.0.1:32026/health` on `backup-blackbird`
   - `/home/ubuntu/services/deerflow/.deploy/production-state.env`
6. If deploy must be undone, use `Roll Back Production`.

Typical operator commands:

```bash
gh run list --repo blackbirdzzzz365-gif/deer-flow --limit 10
gh workflow run "Deploy Production" --repo blackbirdzzzz365-gif/deer-flow --ref main
gh run watch <deploy-run-id> --repo blackbirdzzzz365-gif/deer-flow --exit-status
curl -fsS https://deerflow.blackbirdzzzz.art/health
ssh -p 44518 ubuntu@e1.chiasegpu.vn 'curl -fsS http://127.0.0.1:32026/health'
ssh -p 44518 ubuntu@e1.chiasegpu.vn 'sed -n "1,20p" /home/ubuntu/services/deerflow/.deploy/production-state.env'
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

- Do not deploy DeerFlow production to `linuxvm`.
- Do not revert `PRODUCTION_RUNNER_LABEL` to `linuxvm-primary`.
- Do not revert `PRODUCTION_APP_DIR` to `/home/blackbird/services/deerflow`.
- Do not trigger `Deploy Production` before `Build Production Images` succeeds for the same SHA.
- Do not keep backup-blackbird-only files only on the host. GitHub deploy uses `rsync --delete`, so anything not tracked in the repo can be deleted on the next deploy.
- Do not remove the `nginx` restart from `scripts/deploy_production.sh` unless the upstream routing model changes and is revalidated.
- Keep `deerflow.blackbirdzzzz.art` as the canonical public URL.
- Keep production mounted to `/home/ubuntu/.codex`, `/home/ubuntu/.claude`, and `/home/ubuntu/.openclaw/.env`.

## Rollback

Use GitHub Actions first:

```bash
gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow
gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow -f rollback_sha=<sha>
```

Or directly on the host if necessary:

```bash
ssh -p 44518 ubuntu@e1.chiasegpu.vn '
  cd /home/ubuntu/services/deerflow &&
  scripts/rollback_production.sh
'
```
