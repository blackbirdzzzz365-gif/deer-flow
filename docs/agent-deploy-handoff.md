# DeerFlow Deploy Handoff For Agents

Use this note when an agent needs to deploy DeerFlow after a coding change.

## Current Production Target

- Host role: `compute-primary`
- SSH: `ssh -p 57116 ubuntu@e1.chiasegpu.vn`
- App dir: `/home/blackbird/services/deerflow`
- Public domain: `deerflow.blackbirdzzzz.art`
- GitHub runner label: `compute-primary`

The old `backup-blackbird` route and `ssh -p 44518 ubuntu@e1.chiasegpu.vn` are stale and must not be used for current production work.

## Correct Deploy Sequence

1. Make the code change.
2. Commit and push to `main` if the task explicitly includes deploy-to-production.
3. Wait for both workflows to pass for the same SHA:
   - `CI`
   - `Build Production Images`
4. Trigger `Deploy Production`.
5. Wait for the deploy workflow to finish green.
6. Verify:
   - `curl -fsS https://deerflow.blackbirdzzzz.art/health`
   - `ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird curl -fsS http://127.0.0.1:32026/health'`
   - `ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird sed -n "1,20p" /home/blackbird/services/deerflow/.deploy/production-state.env'`
   - `ssh -p 57116 ubuntu@e1.chiasegpu.vn 'sudo -u blackbird /home/blackbird/bin/prod-audit'`

If you want the repo helper to enforce those gates in one command, run:

```bash
scripts/trigger_production_deploy.sh
```

## Important Project-Specific Facts

- The host `.env` must keep:
  - `APP_DIR=/home/blackbird/services/deerflow`
  - `APP_DOMAIN=deerflow.blackbirdzzzz.art`
- `scripts/deploy_production.sh` defaults to:
  - `DEPLOY_TEMPLATE_DIR=deploy/production`
  - `COMPOSE_FILES=docker-compose.production.yml`
- `Build Production Images` must keep publishing both `linux/amd64` and `linux/arm64`; current compute-primary is `x86_64`, and multi-arch tags keep replacement options open.
- `scripts/deploy_production.sh` must restart `nginx` after `docker compose up -d --remove-orphans`.
- That restart is required because `nginx` can keep a stale Docker upstream IP and otherwise `/health` may return `502` after a rollout.
- GitHub deploy uses `rsync --delete`, so deploy-only files must be committed in the repo, not left only on the host.
- GitHub deploy must exclude `runtime/` from `rsync --delete`; that path is live host state for DeerFlow threads, uploads, and workspaces.

## Do Not Do These Things

- Do not use `backup-blackbird` or `e1.chiasegpu.vn:44518` as the current production target.
- Do not dispatch `Deploy Production` before `Build Production Images` is green for the same SHA.
- Do not change GitHub production vars back to `linuxvm-primary`; DeerFlow's current live target is `compute-primary`.
- Do not remove `deploy/production/` files from the repo.
- Do not remove the `nginx` restart from `scripts/deploy_production.sh`.
- Do not change GitHub production vars back to the stale host paths.

## If You Need To Roll Back

- Preferred path:
  - `gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow`
- Explicit SHA:
  - `gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow -f rollback_sha=<sha>`

## More Detail

If you need the full project deploy truth, read:

- `docs/production-deployment.md`
- `docs/backup-blackbird-migration.md`
