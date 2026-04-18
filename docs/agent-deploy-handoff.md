# DeerFlow Deploy Handoff For Agents

Use this note when an agent needs to deploy DeerFlow after a coding change.

## Current Production Target

- Host: `backup-blackbird`
- SSH: `ssh -p 44518 ubuntu@e1.chiasegpu.vn`
- App dir: `/home/ubuntu/services/deerflow`
- Public domain: `deerflow.blackbirdzzzz.art`
- GitHub runner label: `backup-blackbird-primary`

Production is not on `linuxvm` anymore.

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
   - `ssh -p 44518 ubuntu@e1.chiasegpu.vn 'curl -fsS http://127.0.0.1:32026/health'`
   - `ssh -p 44518 ubuntu@e1.chiasegpu.vn 'sed -n "1,20p" /home/ubuntu/services/deerflow/.deploy/production-state.env'`

## Important Project-Specific Facts

- The host `.env` must keep:
  - `DEPLOY_TEMPLATE_DIR=deploy/backup-blackbird`
  - `COMPOSE_FILES=docker-compose.production.yml,deploy/backup-blackbird/docker-compose.override.yml`
- `scripts/deploy_production.sh` must restart `nginx` after `docker compose up -d --remove-orphans`.
- That restart is required because `nginx` can keep a stale Docker upstream IP and otherwise `/health` may return `502` after a rollout.
- GitHub deploy uses `rsync --delete`, so deploy-only files must be committed in the repo, not left only on the host.
- GitHub deploy must exclude `runtime/` from `rsync --delete`; that path is live host state for DeerFlow threads, uploads, and workspaces.

## Do Not Do These Things

- Do not deploy to `linuxvm`.
- Do not dispatch `Deploy Production` before `Build Production Images` is green for the same SHA.
- Do not remove `deploy/backup-blackbird/` files from the repo.
- Do not remove the `nginx` restart from `scripts/deploy_production.sh`.
- Do not change GitHub production vars back to the old host paths.

## If You Need To Roll Back

- Preferred path:
  - `gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow`
- Explicit SHA:
  - `gh workflow run "Roll Back Production" --repo blackbirdzzzz365-gif/deer-flow -f rollback_sha=<sha>`

## More Detail

If you need the full project deploy truth, read:

- `docs/production-deployment.md`
- `docs/backup-blackbird-migration.md`
