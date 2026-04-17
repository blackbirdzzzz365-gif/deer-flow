# Production Deployment

## Intake block

- project_name: `deer-flow`
- project_slug: `deerflow`
- github_repo: `blackbirdzzzz365-gif/deer-flow`
- app_dir_on_server: `/home/blackbird/services/deerflow`
- app_port: `32026`
- healthcheck_url: `http://127.0.0.1:32026/health`
- runtime: `docker compose`
- env_file_path: `/home/blackbird/services/deerflow/.env`
- has_browser_ui: `false`

## Goal

Production DeerFlow runs from code merged to GitHub `main`, with Linux VM as the primary runtime.

- Primary runtime: `linuxvm`
- Primary app dir: `/home/blackbird/services/deerflow`
- Primary domain: `deerflow.blackbirdzzzz.art`
- Canonical healthcheck: `https://deerflow.blackbirdzzzz.art/health`

## Source of truth

- Production branch: `main`
- Backend image registry: `ghcr.io/blackbirdzzzz365-gif/deer-flow-backend`
- Frontend image registry: `ghcr.io/blackbirdzzzz365-gif/deer-flow-frontend`
- Production compose: `docker-compose.production.yml`
- Primary env file: `/home/blackbird/services/deerflow/.env`
- Env template: `deploy/production/app.env.example`
- Runtime config template: `deploy/production/config.template.yaml`
- Runtime extensions template: `deploy/production/extensions_config.template.json`

## Runtime posture

- The public UI and API share one hostname through the nginx container.
- The backend and LangGraph containers mount `~/.codex` and `~/.claude` from `linuxvm`.
- The default production model set uses:
  - `gpt-5.4` via `CodexChatModel`
  - `claude-sonnet-4.6` via `ClaudeChatModel`
- Sandbox execution uses DeerFlow's Docker AIO sandbox through the host Docker socket.

## Required server env

Primary `.env`:

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
```

`BETTER_AUTH_SECRET` is generated automatically by `scripts/deploy_production.sh` and persisted under `.deploy/`.

## Deploy flow

1. Merge or push the target commit to `main`.
2. `build-image.yml` publishes multi-arch images for:
   - `linux/arm64` on primary `linuxvm`
   - `linux/amd64` for future standby compatibility
3. `deploy-production.yml` syncs the repo to `/home/blackbird/services/deerflow`.
4. The workflow writes `.deploy/deploy.env`, pulls GHCR images, and runs:
   - `docker compose -f docker-compose.production.yml pull`
   - `docker compose -f docker-compose.production.yml up -d --remove-orphans`
5. `scripts/healthcheck_production.sh` validates:
   - local: `http://127.0.0.1:32026/health`
   - public: `https://deerflow.blackbirdzzzz.art/health`
6. Deployment state is persisted in `.deploy/production-state.env`.

## Rollback

- Default rollback target: `PREVIOUS_SHA`
- Explicit rollback target: `ROLLBACK_SHA=<sha>`

Use:

```bash
scripts/rollback_production.sh
scripts/rollback_production.sh <sha>
```

Or via GitHub Actions:

```bash
scripts/trigger_production_rollback.sh
scripts/trigger_production_rollback.sh <sha>
```

## Rules

- Do not build production from local source on `linuxvm`.
- Keep production tied to `main` and GHCR SHA-tagged images.
- Keep `deerflow.blackbirdzzzz.art` as the canonical public URL.
- Preserve the host-mounted Codex and Claude auth directories on `linuxvm`.
- Finish production verification with `ssh linuxvm '~/bin/prod-audit'`.
