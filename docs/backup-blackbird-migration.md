# Backup-Blackbird Migration Checklist

Historical note as of `2026-04-26`: this document is an attempted migration runbook, not the current production truth.
Canonical production is on `linuxvm`, the public domain `deerflow.blackbirdzzzz.art` is routed there, and `ssh -p 44518 ubuntu@e1.chiasegpu.vn` is not a working production SSH path.
Use `docs/production-deployment.md` for current deploy and rollback operations.

This runbook moves DeerFlow production from `linuxvm` to `backup-blackbird`
(`ssh -p 44518 ubuntu@e1.chiasegpu.vn`) while keeping the Docker + GHCR deploy path.

## Assumptions

- Primary source runtime today: `linuxvm`
- Target runtime: `backup-blackbird`
- Target app dir: `/home/ubuntu/services/deerflow`
- Temporary rehearsal hostname: `deerflow-standby.blackbirdzzzz.art`
- Canonical production hostname after cutover: `deerflow.blackbirdzzzz.art`

## 0. Preflight

Run from the local operator machine:

```bash
ssh linuxvm 'hostname && whoami && pwd'
ssh -p 44518 ubuntu@e1.chiasegpu.vn 'hostname && whoami && pwd'
ssh linuxvm 'df -h / && free -h'
ssh -p 44518 ubuntu@e1.chiasegpu.vn 'df -h / && free -h'
```

Expected:

- source host resolves to `openclawlinus`
- target host resolves to `backup-blackbird`
- target has at least ~15G disk free before pulling DeerFlow images + sandbox

## 1. Capture the current DeerFlow deploy version

```bash
ssh linuxvm '
  cd /home/blackbird/services/deerflow &&
  source .deploy/production-state.env &&
  printf "DEPLOY_SHA=%s\nBACKEND_IMAGE_REF=%s\nFRONTEND_IMAGE_REF=%s\n" \
    "$CURRENT_SHA" "$CURRENT_BACKEND_IMAGE_REF" "$CURRENT_FRONTEND_IMAGE_REF"
'
```

Export those values locally before continuing:

```bash
export DEPLOY_SHA=<current-sha>
export BACKEND_IMAGE_REF=<current-backend-image-ref>
export FRONTEND_IMAGE_REF=<current-frontend-image-ref>
export STANDBY_SSH='ssh -p 44518 ubuntu@e1.chiasegpu.vn'
export STANDBY_APP_DIR=/home/ubuntu/services/deerflow
```

## 2. Prepare the target directories

```bash
$STANDBY_SSH '
  mkdir -p \
    /home/ubuntu/services/deerflow \
    /home/ubuntu/services/deerflow/.deploy \
    /home/ubuntu/services/deerflow/config \
    /home/ubuntu/services/deerflow/runtime \
    /home/ubuntu/.codex \
    /home/ubuntu/.claude \
    /home/ubuntu/.openclaw
'
```

## 3. Sync the repo content to backup-blackbird

Use the checked-out local repo as the source of code and deploy templates:

```bash
rsync -az --delete \
  -e "ssh -p 44518" \
  --exclude ".git" \
  --exclude "node_modules" \
  --exclude ".venv" \
  ./ \
  ubuntu@e1.chiasegpu.vn:${STANDBY_APP_DIR}/
```

## 4. Sync host-bound runtime material from linuxvm

These mounts are required because DeerFlow production currently depends on host-side
Codex/Claude auth and existing deploy secrets.

```bash
mkdir -p /tmp/deerflow-migration/{codex,claude,deploy}
rsync -az linuxvm:/home/blackbird/.codex/ /tmp/deerflow-migration/codex/
rsync -az linuxvm:/home/blackbird/.claude/ /tmp/deerflow-migration/claude/
rsync -az linuxvm:/home/blackbird/services/deerflow/.deploy/ /tmp/deerflow-migration/deploy/
rsync -az linuxvm:/home/blackbird/.openclaw/.env /tmp/deerflow-migration/openclaw.env
rsync -az -e "ssh -p 44518" /tmp/deerflow-migration/codex/ ubuntu@e1.chiasegpu.vn:/home/ubuntu/.codex/
rsync -az -e "ssh -p 44518" /tmp/deerflow-migration/claude/ ubuntu@e1.chiasegpu.vn:/home/ubuntu/.claude/
rsync -az -e "ssh -p 44518" /tmp/deerflow-migration/deploy/ ubuntu@e1.chiasegpu.vn:${STANDBY_APP_DIR}/.deploy/
scp -P 44518 /tmp/deerflow-migration/openclaw.env ubuntu@e1.chiasegpu.vn:/home/ubuntu/.openclaw/.env
```

Optional: sync runtime state if you want to keep chat history, checkpoints, and memory:

```bash
rsync -az --delete \
  -e "ssh -p 44518" \
  linuxvm:/home/blackbird/services/deerflow/runtime/ \
  ubuntu@e1.chiasegpu.vn:${STANDBY_APP_DIR}/runtime/
```

If you prefer a cold-start runtime on the new host, skip the optional runtime sync.

## 5. Render the backup-blackbird env file

Start from the prepared backup template:

```bash
scp -P 44518 deploy/backup-blackbird/app.env.example ubuntu@e1.chiasegpu.vn:${STANDBY_APP_DIR}/.env
```

Copy current production-only secrets from the source host:

```bash
ssh linuxvm "grep -E '^(NINEROUTER_API_KEY|XAI_BASE_URL|XAI_X_SEARCH_MODEL|XAI_X_SEARCH_MAX_TURNS|XAI_X_SEARCH_TIMEOUT_SECONDS|XAI_X_SEARCH_INLINE_CITATIONS)=' /home/blackbird/services/deerflow/.env" \
  > /tmp/deerflow-runtime-secrets.env
scp -P 44518 /tmp/deerflow-runtime-secrets.env ubuntu@e1.chiasegpu.vn:${STANDBY_APP_DIR}/runtime-secrets.env
$STANDBY_SSH "cat ${STANDBY_APP_DIR}/runtime-secrets.env >> ${STANDBY_APP_DIR}/.env && rm -f ${STANDBY_APP_DIR}/runtime-secrets.env"
```

For rehearsal, keep these values in `${STANDBY_APP_DIR}/.env`:

- `APP_DOMAIN=deerflow-standby.blackbirdzzzz.art`
- `PRODUCTION_HEALTHCHECK_URL=https://deerflow-standby.blackbirdzzzz.art/health`
- `REQUIRE_PUBLIC_HEALTHCHECK=0`

After final DNS/tunnel cutover, switch them to:

```env
APP_DOMAIN=deerflow.blackbirdzzzz.art
PRODUCTION_HEALTHCHECK_URL=https://deerflow.blackbirdzzzz.art/health
REQUIRE_PUBLIC_HEALTHCHECK=1
```

## 6. Pre-pull the required images on backup-blackbird

```bash
$STANDBY_SSH "
  docker pull ${BACKEND_IMAGE_REF} &&
  docker pull ${FRONTEND_IMAGE_REF} &&
  docker pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
"
```

## 7. Rehearsal deploy on backup-blackbird

The deploy scripts now accept template and compose variants from `.env`, so the
backup host can reuse the same script entrypoint:

```bash
$STANDBY_SSH "
  cd ${STANDBY_APP_DIR} &&
  DEPLOY_SHA=${DEPLOY_SHA} \
  BACKEND_IMAGE_REF=${BACKEND_IMAGE_REF} \
  FRONTEND_IMAGE_REF=${FRONTEND_IMAGE_REF} \
  APP_DIR=${STANDBY_APP_DIR} \
  scripts/deploy_production.sh
"
```

What this does on backup-blackbird:

- uses `deploy/backup-blackbird/config.template.yaml`
- uses `docker-compose.production.yml` plus `deploy/backup-blackbird/docker-compose.override.yml`
- keeps sandbox replicas at `1`
- skips public healthcheck until you explicitly turn it back on

## 8. Smoke test the target host before cutover

```bash
$STANDBY_SSH "
  cd ${STANDBY_APP_DIR} &&
  docker compose \
    --env-file .env \
    --env-file .deploy/deploy.env \
    -f docker-compose.production.yml \
    -f deploy/backup-blackbird/docker-compose.override.yml \
    ps
"
$STANDBY_SSH "curl -fsS http://127.0.0.1:32026/health"
curl -fsS https://deerflow-standby.blackbirdzzzz.art/health
```

Then run one real tool-enabled DeerFlow chat against the standby hostname and confirm:

- frontend loads
- normal prompt works
- tool prompt reaches sandbox successfully
- no `Sandbox ... failed to become ready within timeout`

## 9. Cut over public traffic

Only after rehearsal is clean:

1. Point Cloudflare Tunnel / public route for `deerflow.blackbirdzzzz.art` to `backup-blackbird`
2. Update `${STANDBY_APP_DIR}/.env`:

```bash
$STANDBY_SSH "
  python3 - <<'PY'
from pathlib import Path
env_path = Path('${STANDBY_APP_DIR}/.env')
text = env_path.read_text()
text = text.replace('APP_DOMAIN=deerflow-standby.blackbirdzzzz.art', 'APP_DOMAIN=deerflow.blackbirdzzzz.art')
text = text.replace('PRODUCTION_HEALTHCHECK_URL=https://deerflow-standby.blackbirdzzzz.art/health', 'PRODUCTION_HEALTHCHECK_URL=https://deerflow.blackbirdzzzz.art/health')
text = text.replace('REQUIRE_PUBLIC_HEALTHCHECK=0', 'REQUIRE_PUBLIC_HEALTHCHECK=1')
env_path.write_text(text)
PY
"
```

3. Re-run deploy to force post-cutover validation:

```bash
$STANDBY_SSH "
  cd ${STANDBY_APP_DIR} &&
  DEPLOY_SHA=${DEPLOY_SHA} \
  BACKEND_IMAGE_REF=${BACKEND_IMAGE_REF} \
  FRONTEND_IMAGE_REF=${FRONTEND_IMAGE_REF} \
  APP_DIR=${STANDBY_APP_DIR} \
  scripts/deploy_production.sh
"
```

## 10. Observe before draining linuxvm

Keep `linuxvm` untouched for a short burn-in window and verify:

```bash
curl -fsS https://deerflow.blackbirdzzzz.art/health
$STANDBY_SSH "docker stats --no-stream"
```

Run at least:

- one normal chat
- one tool-heavy chat
- one x_search / MCP-assisted flow if used

## 11. Drain DeerFlow from linuxvm

Only after the new primary is stable:

```bash
ssh linuxvm '
  cd /home/blackbird/services/deerflow &&
  docker compose --env-file .env --env-file .deploy/deploy.env -f docker-compose.production.yml down
'
ssh linuxvm 'docker image rm ghcr.io/blackbirdzzzz365-gif/deer-flow-backend:sha-'\"${DEPLOY_SHA}\"' || true'
ssh linuxvm 'docker image rm ghcr.io/blackbirdzzzz365-gif/deer-flow-frontend:sha-'\"${DEPLOY_SHA}\"' || true'
ssh linuxvm 'docker image rm enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest || true'
ssh linuxvm 'sudo rm -rf /home/blackbird/services/deerflow'
ssh linuxvm 'df -h /'
```

## 12. Rollback path

If backup-blackbird fails before cutover, stop there and keep `linuxvm` as-is.

If backup-blackbird fails after cutover:

1. switch Cloudflare/public route back to `linuxvm`
2. on `backup-blackbird`, roll back the container version if needed:

```bash
$STANDBY_SSH "
  cd ${STANDBY_APP_DIR} &&
  APP_DIR=${STANDBY_APP_DIR} \
  scripts/rollback_production.sh
"
```

3. if needed, bring `linuxvm` DeerFlow back up:

```bash
ssh linuxvm '
  cd /home/blackbird/services/deerflow &&
  docker compose --env-file .env --env-file .deploy/deploy.env -f docker-compose.production.yml up -d --remove-orphans
'
```
