# OpenHands + Feynman Independent Review Packet

## Status

- File date log: `2026-04-26`
- Time zone: `Asia/Ho_Chi_Minh`
- File purpose: handoff packet for an independent reviewer to review the OpenHands/Feynman integration work
- Scope: local implementation snapshot for OpenHands + Feynman integration into DeerFlow
- Snapshot branch: `codex/openhands-feynman-dev-ready-spec`
- Snapshot truth at the time of this file:
  - this work is **not yet merged** into `main`
  - this work is **not yet production-built/deployed** as part of the DeerFlow production flow
  - current production truth still follows `main`, not this local snapshot

## Review Fix Pass Log

- Fix pass date: `2026-04-26`
- Trigger: independent review findings F1-F13
- Fix scope completed in this pass:
  - production `deploy/production` templates now expose OpenHands and Feynman config
  - production env example now documents required `OPENHANDS_*` and `FEYNMAN_MODEL` values
  - `scripts/deploy_production.sh` now migrates missing delegated-runtime config sections into an existing production `config.yaml`
  - deploy now creates and validates writable OpenHands/Feynman home directories before restarting nginx
  - invalid ACP `thread_id` falls back to the global ACP workspace instead of bubbling an uncaught exception
  - delegated runtime `run_id` values now include microseconds plus a short random suffix
  - `copy_seed_paths` now preserves `/mnt/user-data` namespace paths under the delegated input directory
  - Feynman stdout/stderr is streamed into `run.log` while the process runs, so timeout results keep partial diagnostics
  - delegated runtime started events now carry the effective prompt that is actually sent to the subprocess
  - frontend `SubtaskCard` now handles missing subtask state without throwing
  - artifact exclusion now only filters reserved root runtime files, not nested user artifacts with the same basename
- Fix verification snapshot:
  - targeted OpenHands/Feynman backend tests passed: `47 passed`
  - backend non-live suite passed: `1979 passed, 17 skipped, 19 deselected`
  - frontend `typecheck` passed
  - frontend `vitest` passed: `19 passed`
  - frontend production build passed with dummy `BETTER_AUTH_SECRET`

### Second Review Fix Pass

- Fix pass date: `2026-04-26`
- Trigger: follow-up independent review findings after F1-F13 fix pass
- Fix scope completed in this pass:
  - `SubtaskCard` no longer returns before a later hook call; the status icon is rendered without `useMemo`, preserving hook order when subtask state appears after first render
  - production deploy migration now validates required delegated-runtime config content, not just block presence; stale or partial existing `acp_agents.openhands` or `feynman` blocks fail before container restart instead of deploying silently
  - delegated runtime progress/completed events no longer clear the effective prompt stored by the started event
  - OpenHands workspace docs now specify per-run output isolation under `/mnt/acp-workspace/deerflow/{run_id}/`
- Fix verification snapshot:
  - `bash -n scripts/deploy_production.sh` passed
  - targeted deploy/runtime backend tests passed: `33 passed`
  - targeted integration backend tests passed: `47 passed`
  - backend non-live suite passed: `1979 passed, 17 skipped, 19 deselected`
  - frontend `typecheck` passed
  - frontend `vitest` passed: `19 passed`
  - frontend production build passed with dummy `BETTER_AUTH_SECRET`
  - production config template loaded through `deerflow.config.app_config` with `feynman.enabled=True`

## Why This File Exists

This file tells an independent reviewer exactly:

1. what they are reviewing
2. which documents they must read first
3. which code paths matter most
4. which risks are already known
5. what extra materials must be provided if the reviewer does not have direct access to this local workspace

This packet is intentionally explicit because the current work is still a local branch/worktree snapshot, not a merged production change set.

## Reviewer Read Order

The reviewer should read in this exact order.

1. Architecture intent:
   - [2026-04-19-openhands-feynman-solution-architecture.md](/Users/nguyenquocthong/project/2-deer-flow/docs/plans/2026-04-19-openhands-feynman-solution-architecture.md)
2. Implementation plan:
   - [2026-04-19-openhands-feynman-implementation-detailed.md](/Users/nguyenquocthong/project/2-deer-flow/docs/plans/2026-04-19-openhands-feynman-implementation-detailed.md)
3. Exact implementation contract:
   - [2026-04-19-openhands-feynman-low-level-spec.md](/Users/nguyenquocthong/project/2-deer-flow/docs/plans/2026-04-19-openhands-feynman-low-level-spec.md)
4. Production deployment contract for this repo:
   - [production-deployment.md](/Users/nguyenquocthong/project/2-deer-flow/docs/production-deployment.md)
5. This review packet:
   - [2026-04-26-openhands-feynman-review-packet.md](/Users/nguyenquocthong/project/2-deer-flow/docs/plans/2026-04-26-openhands-feynman-review-packet.md)

The reviewer should not start from raw code first. They should lock the intended contract from the 3 design/spec docs above before checking implementation.

## Review Scope

The intended V1 shape is:

- DeerFlow remains the top-level orchestrator
- OpenHands integrates through the existing ACP surface
- Feynman integrates as a first-class DeerFlow delegated CLI tool
- both runtimes produce deterministic artifacts and progress events
- frontend renders delegated runtime progress through subtask cards
- backend image and production config are updated so the runtimes are operable in containerized production

The reviewer should explicitly validate that the code still matches that shape and has not drifted into a different orchestration model.

## Code Areas The Reviewer Must Inspect

### Backend runtime and contracts

- [delegated_runtime_support.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/tools/delegated_runtime_support.py)
- [invoke_acp_agent_tool.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py)
- [invoke_feynman_tool.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/tools/builtins/invoke_feynman_tool.py)
- [tools.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/tools/tools.py)
- [prompt.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/agents/lead_agent/prompt.py)
- [app_config.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/config/app_config.py)
- [feynman_config.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/config/feynman_config.py)
- [paths.py](/Users/nguyenquocthong/project/2-deer-flow/backend/packages/harness/deerflow/config/paths.py)

### Frontend event and progress rendering

- [hooks.ts](/Users/nguyenquocthong/project/2-deer-flow/frontend/src/core/threads/hooks.ts)
- [message-list.tsx](/Users/nguyenquocthong/project/2-deer-flow/frontend/src/components/workspace/messages/message-list.tsx)
- [subtask-card.tsx](/Users/nguyenquocthong/project/2-deer-flow/frontend/src/components/workspace/messages/subtask-card.tsx)
- [context.tsx](/Users/nguyenquocthong/project/2-deer-flow/frontend/src/core/tasks/context.tsx)
- [types.ts](/Users/nguyenquocthong/project/2-deer-flow/frontend/src/core/tasks/types.ts)
- [utils.ts](/Users/nguyenquocthong/project/2-deer-flow/frontend/src/core/messages/utils.ts)

### Config, packaging, and production surfaces

- [backend/Dockerfile](/Users/nguyenquocthong/project/2-deer-flow/backend/Dockerfile)
- [config.example.yaml](/Users/nguyenquocthong/project/2-deer-flow/config.example.yaml)
- [docker-compose.production.yml](/Users/nguyenquocthong/project/2-deer-flow/docker-compose.production.yml)
- [config.template.yaml](/Users/nguyenquocthong/project/2-deer-flow/deploy/backup-blackbird/config.template.yaml)
- [app.env.example](/Users/nguyenquocthong/project/2-deer-flow/deploy/backup-blackbird/app.env.example)
- [deploy_production.sh](/Users/nguyenquocthong/project/2-deer-flow/scripts/deploy_production.sh)
- [delegated-runtime-routing skill](/Users/nguyenquocthong/project/2-deer-flow/skills/custom/delegated-runtime-routing/SKILL.md)

### Tests the reviewer should inspect

- [test_delegated_runtime_support.py](/Users/nguyenquocthong/project/2-deer-flow/backend/tests/test_delegated_runtime_support.py)
- [test_invoke_acp_agent_tool.py](/Users/nguyenquocthong/project/2-deer-flow/backend/tests/test_invoke_acp_agent_tool.py)
- [test_invoke_feynman_tool.py](/Users/nguyenquocthong/project/2-deer-flow/backend/tests/test_invoke_feynman_tool.py)
- [test_app_config_reload.py](/Users/nguyenquocthong/project/2-deer-flow/backend/tests/test_app_config_reload.py)
- [test_lead_agent_prompt.py](/Users/nguyenquocthong/project/2-deer-flow/backend/tests/test_lead_agent_prompt.py)

## Current Known Status The Reviewer Must Know Up Front

At the time of this file on `2026-04-26`:

- this integration work is still a local review candidate, not a merged release
- no valid statement should be made that OpenHands/Feynman integration is already on production
- production currently serves DeerFlow from `main`, not from this local branch snapshot

This distinction matters because the reviewer must review the code itself, not infer correctness from the current production environment.

## Known Risks Already Identified Before Independent Review

The reviewer should verify these areas carefully because they are already suspected to be weak points.

1. `run_id` collision risk
   - In `delegated_runtime_support.create_run_id()`, the current `run_id` format is based on timestamp to the second plus slug.
   - If multiple delegated runs with the same description start in the same second, two runs can target the same directory.
   - Reviewer should decide whether this is acceptable or must be fixed before merge.

2. `seed_paths` basename collision risk
   - In `copy_seed_paths()`, files/directories are copied to `destination_dir / source.name`.
   - Two different source paths with the same basename can overwrite each other silently.
   - Reviewer should check whether path preservation or collision detection is required.

3. ACP invalid `thread_id` handling gap
   - `invoke_acp_agent()` creates a delegated ACP run before fallback behavior from `_get_work_dir()` can protect invalid `thread_id`.
   - Reviewer should check whether ACP delegated-run creation must share the same graceful fallback contract.

4. Feynman timeout observability gap
   - Feynman timeout handling currently does not guarantee partial stdout preservation before process termination.
   - Reviewer should decide whether current timeout logging is sufficient for production debugging.

These are not theoretical architecture comments. They are concrete implementation review points.

## What “Good Review” Should Answer

The reviewer should explicitly answer these questions in writing.

1. Does DeerFlow remain the real orchestrator, or has orchestration leaked into OpenHands/Feynman?
2. Is the delegated runtime filesystem contract deterministic, traceable, and safe under concurrency?
3. Are the runtime events sufficient for frontend progress rendering and post-run inspection?
4. Is the OpenHands ACP contract specific enough to avoid ambiguous outputs?
5. Is the Feynman tool constrained enough for safe V1 rollout?
6. Are config and deploy changes sufficient for containerized production use?
7. Are the current tests strong enough, and which missing tests are release blockers?
8. Which issues must be fixed before merge, and which can be accepted as V1 debt?

## Verification Snapshot To Give The Reviewer

If the reviewer is reviewing the same local snapshot, they should also be given the latest recorded local verification summary for this work:

- targeted OpenHands/Feynman integration tests passed
- backend non-live suite passed
- frontend `typecheck`, `vitest`, and production build passed
- live/production truth was not used as evidence that this local branch was deployed

If the reviewer wants exact command evidence, provide the exact command transcript or rerun the commands in front of them.

## Materials You Must Provide To The Reviewer

If the reviewer has direct access to this same local repository and worktree, provide:

- this file
- the 3 design/spec docs
- the exact branch name
- the current `git status --short`

If the reviewer does **not** have access to this same local worktree, you must also provide:

- a patch or diff bundle of the current local changes
- a file list of modified and untracked files
- the latest test command outputs

Because the current work is not yet merged into `main`, sending only a branch name is not sufficient if the branch tip does not contain all local uncommitted changes.

## Minimal Reviewer Handoff Checklist

Before asking the reviewer to start, confirm you have sent all items below.

- [ ] branch name: `codex/openhands-feynman-dev-ready-spec`
- [ ] this review packet
- [ ] architecture doc
- [ ] implementation detailed doc
- [ ] low-level spec
- [ ] production deployment doc
- [ ] code diff or patch of current local changes
- [ ] current git status
- [ ] latest verification outputs
- [ ] note stating clearly that the work is not yet merged to `main` and not yet production deployed

## Reviewer Output Format Requested

Ask the reviewer to return feedback in this structure:

1. merge blockers
2. correctness risks
3. production/deploy risks
4. missing tests
5. design drift from the approved docs
6. optional improvements that are not blockers

This format prevents the review from collapsing into generic commentary.

## Change Control Note

If this file is edited later, the `File date log` at the top must also be updated so the reviewer knows exactly which snapshot they are reading.
