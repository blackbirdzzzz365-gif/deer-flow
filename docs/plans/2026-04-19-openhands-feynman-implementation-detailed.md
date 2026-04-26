# OpenHands + Feynman Integration Detailed Implementation Plan

## Status

- Date: `2026-04-19`
- Scope: implementation-ready plan for the architecture in `docs/plans/2026-04-19-openhands-feynman-solution-architecture.md`
- Low-level handoff spec: `docs/plans/2026-04-19-openhands-feynman-low-level-spec.md`

## Implementation Objectives

Implement the integration in a way that:

- fits the current DeerFlow 2 codebase
- reuses `task()`, `invoke_acp_agent`, the sandbox path model, and streaming
- gives the lead agent better routing instead of just more tools
- adds enough structure for artifact collection and progress, without creating a separate runtime service

## Final V1 Shape

After V1, the repo should have:

- `OpenHands` configured as an ACP agent named `openhands`
- a new built-in `invoke_feynman` tool
- a shared delegated-runtime helper module
- runtime-routing guidance in the lead-agent layer
- frontend support for delegated-runtime custom events
- docs and config examples that make the feature operable end-to-end

## Phase Order

1. Add shared delegated-runtime support primitives.
2. Enhance ACP invocation for OpenHands.
3. Add native Feynman CLI tool.
4. Teach the lead agent when to use each runtime.
5. Add frontend progress handling and polish.
6. Harden with tests, timeouts, and cleanup.

## Phase 1: Shared Delegated-Runtime Support

### Goal

Avoid duplicating workspace, manifest, and custom-event logic across OpenHands and Feynman.

### Files to add

- `backend/packages/harness/deerflow/tools/delegated_runtime_support.py`

### Responsibilities of the helper module

- create deterministic run IDs
- create delegated run directories
- write `task.md`
- copy selected context files into a run-local `context/` or `inputs/` directory
- write `deerflow-result.json`
- emit runtime events through `get_stream_writer()`
- collect artifacts by glob
- clean up stale run directories when configured

### Suggested helper API

```python
@dataclass
class DelegatedRunPaths:
    runtime: str
    run_id: str
    host_dir: Path
    virtual_dir: str
    task_file: Path
    result_file: Path
    log_file: Path

def create_delegated_run(
    runtime: str,
    thread_id: str,
    *,
    slug: str | None = None,
    location: Literal["workspace", "acp"] = "workspace",
) -> DelegatedRunPaths: ...

def copy_seed_paths(
    thread_data: ThreadDataState,
    seed_paths: list[str],
    dest_dir: Path,
) -> list[str]: ...

def emit_runtime_event(
    event_type: str,
    *,
    runtime: str,
    run_id: str,
    description: str,
    message: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None: ...
```

### Directory policy

For runtime locations:

- `workspace` location:
  - host: `backend/.deer-flow/threads/{thread_id}/user-data/workspace/.delegated/{runtime}/{run-id}-{slug}/`
  - virtual: `/mnt/user-data/workspace/.delegated/{runtime}/{run-id}-{slug}/`
- `acp` location:
  - host: `backend/.deer-flow/threads/{thread_id}/acp-workspace/`
  - virtual: `/mnt/acp-workspace/`

### Tests to add

- `backend/tests/test_delegated_runtime_support.py`

Cover:

- run-id and slug normalization
- directory creation
- safe copying from `/mnt/user-data/*`
- traversal rejection
- deterministic manifest writing

## Phase 2: OpenHands via Enhanced ACP

### Goal

Turn the existing ACP integration into a usable OpenHands specialist path instead of a raw text-only subprocess call.

### Files to change

- `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py`
- `backend/packages/harness/deerflow/tools/tools.py`
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
- `config.example.yaml`
- `backend/tests/test_invoke_acp_agent_tool.py`

### Keep

- `invoke_acp_agent` remains the public tool surface for ACP runtimes
- `acp_agents` remains the config entry point

### Extend the input schema

Change the ACP tool input model from:

```python
class _InvokeACPAgentInput(BaseModel):
    agent: str
    prompt: str
```

to:

```python
class _InvokeACPAgentInput(BaseModel):
    agent: str
    prompt: str
    seed_paths: list[str] = Field(
        default_factory=list,
        description="Optional /mnt/user-data files or directories to copy into the ACP workspace before launch",
    )
    expected_outputs: list[str] = Field(
        default_factory=list,
        description="Optional relative paths the agent should create under the ACP workspace",
    )
```

### Required ACP behavior changes

#### 1. Seed context into ACP workspace

Before spawning the ACP process:

- resolve `seed_paths`
- copy them into `<acp-workspace>/inputs/{run_id}/`
- append a standard note to the effective prompt:
  - input files are available under `./inputs/{run_id}`
  - write requested deliverables under `./deerflow/{run_id}`

This solves the current limitation that the lead agent cannot write directly to `/mnt/acp-workspace`.

#### 2. Standardize the OpenHands deliverable contract

When `agent == "openhands"`, append a standard DeerFlow contract to the prompt:

- write a short summary to `deerflow/summary.md`
- write machine-readable artifact metadata to `deerflow/artifacts.json`
- if code changes are proposed, write `deerflow/patch.diff`
- if browser evidence matters, write screenshots under `deerflow/screenshots/`

#### 3. Emit runtime lifecycle events

Emit:

- `delegated_runtime_started`
- `delegated_runtime_progress`
- `delegated_runtime_completed`
- `delegated_runtime_failed`

V1 can keep progress coarse:

- started
- prompt sent
- final response collected
- completed or failed

#### 4. Return a richer final message

Instead of returning raw final text only, return:

- final response text
- any discovered deliverable paths under `/mnt/acp-workspace/deerflow/{run_id}/...`

Example shape:

```text
OpenHands completed.

Summary:
<agent text>

Artifacts:
- /mnt/acp-workspace/deerflow/{run_id}/summary.md
- /mnt/acp-workspace/deerflow/{run_id}/artifacts.json
- /mnt/acp-workspace/deerflow/{run_id}/patch.diff
```

### Recommended `config.yaml` example

```yaml
acp_agents:
  openhands:
    command: openhands
    args: ["acp", "--always-approve"]
    description: OpenHands for isolated coding, browser debugging, and patch generation
    auto_approve_permissions: true
```

### Acceptance criteria

- DeerFlow can invoke `openhands` through `invoke_acp_agent`
- selected `/mnt/user-data` files can be seeded into ACP workspace
- DeerFlow can read artifacts back from `/mnt/acp-workspace`
- custom events reach the frontend

### Tests

Extend `backend/tests/test_invoke_acp_agent_tool.py` to cover:

- `seed_paths` copy behavior
- prompt augmentation for OpenHands
- lifecycle custom events
- artifact path rendering
- invalid seed path rejection

## Phase 3: Add Native Feynman Tool

### Goal

Integrate Feynman as a real delegated runtime, not as a skill-only prompt bundle and not as a raw shell command.

### Files to add

- `backend/packages/harness/deerflow/config/feynman_config.py`
- `backend/packages/harness/deerflow/tools/builtins/invoke_feynman_tool.py`
- `backend/tests/test_invoke_feynman_tool.py`

### Files to change

- `backend/packages/harness/deerflow/tools/builtins/__init__.py`
- `backend/packages/harness/deerflow/tools/tools.py`
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
- `config.example.yaml`

### New config section

Add a dedicated Feynman config section to `config.example.yaml`:

```yaml
feynman:
  enabled: false
  command: feynman
  args: []
  timeout_seconds: 1800
  env: {}
  default_workflow: deepresearch
```

Reason for a dedicated section:

- only one non-ACP runtime is being added in V1
- configuration stays simpler than introducing a generic runtime registry now

### Public tool contract

Add a new built-in tool:

```python
class _InvokeFeynmanInput(BaseModel):
    workflow: Literal["deepresearch", "lit", "review", "audit", "compare", "draft"]
    objective: str
    slug: str | None = None
    seed_paths: list[str] = Field(default_factory=list)
```

V1 should explicitly exclude:

- `replicate`
- `autoresearch`
- `watch`

Reason:

- they imply long-running loops, compute provisioning, or recurring runs
- they deserve a separate lifecycle and policy discussion

### Execution algorithm

1. Resolve `thread_id`.
2. Create delegated run dir under `/mnt/user-data/workspace/.delegated/feynman/...`.
3. Copy seed files into `context/`.
4. Write `task.md` with:
   - objective
   - workflow
   - DeerFlow output expectations
5. Spawn the CLI:
   - `feynman <workflow> "<objective>"`
6. Stream stdout/stderr lines into `delegated_runtime_progress`.
7. On completion, scan for:
   - `outputs/**/*.md`
   - `papers/**/*.md`
   - `notes/**/*.md`
   - `**/*.provenance.md`
8. Write `deerflow-result.json`.
9. Return a concise summary with virtual paths into DeerFlow workspace.

### Normalized output policy

The tool should not dump the entire workspace inline.

Return:

- the run directory
- the most relevant summary or final brief path
- the artifact count
- a short execution summary

Example:

```text
Feynman completed.

Run directory:
- /mnt/user-data/workspace/.delegated/feynman/rtm_123-rlhf-alternatives

Key artifacts:
- /mnt/user-data/workspace/.delegated/feynman/rtm_123-rlhf-alternatives/outputs/rlhf-alternatives-brief.md
- /mnt/user-data/workspace/.delegated/feynman/rtm_123-rlhf-alternatives/outputs/rlhf-alternatives-verification.md
- /mnt/user-data/workspace/.delegated/feynman/rtm_123-rlhf-alternatives/outputs/rlhf-alternatives.provenance.md
```

### Acceptance criteria

- DeerFlow can invoke the host `feynman` CLI through a first-class tool
- the run stays inside DeerFlow-visible workspace
- artifacts are discoverable and easy for the lead agent to read
- unsupported workflows are rejected early

### Tests

`backend/tests/test_invoke_feynman_tool.py` should cover:

- disabled config
- command-not-found handling
- run-dir creation
- workflow allowlist enforcement
- seed file copying
- artifact discovery
- timeout handling
- progress event emission

## Phase 4: Teach DeerFlow to Use the Runtimes Well

### Goal

Adding tools is not enough. The lead agent must learn when not to use them.

### Files to change

- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
- `skills/custom/delegated-runtime-routing/SKILL.md`
- optionally `backend/docs/CONFIGURATION.md`

### Prompt changes

Add a short runtime routing section to the lead prompt:

- use direct DeerFlow tools first for small local tasks
- use `invoke_feynman` for evidence-heavy research and cited synthesis
- use `invoke_acp_agent` with `agent="openhands"` for isolated coding/browser/repo tasks
- after delegated completion, inspect artifacts and synthesize before replying

### Skill changes

Add a repo-local skill `skills/custom/delegated-runtime-routing/SKILL.md` that gives:

- routing heuristics
- per-runtime output contract
- examples of when to use each runtime
- examples of when not to delegate

This keeps routing logic editable without growing the hardcoded system prompt too aggressively.

### Optional custom agents

Custom agents are optional packaging, not hard isolation.

If desired later:

- `research-pro`
- `implementation-pro`

Use them for UX packaging, not for security boundaries.

## Phase 5: Frontend and Streaming UX

### Goal

Show delegated-runtime progress in the existing chat UI instead of hiding it in backend logs.

### Files to change

- `frontend/src/core/threads/hooks.ts`
- `frontend/src/core/tasks/types.ts`
- `frontend/src/components/workspace/messages/message-list.tsx`
- `frontend/src/core/i18n/locales/en-US.ts`
- `frontend/src/core/i18n/locales/zh-CN.ts`

### Minimal frontend strategy

Reuse the existing subtask model for delegated runtimes.

`onCustomEvent` in `frontend/src/core/threads/hooks.ts` should handle:

- `delegated_runtime_started`
- `delegated_runtime_progress`
- `delegated_runtime_completed`
- `delegated_runtime_failed`

Map them into the existing `Subtask` state:

- `id` = runtime `run_id`
- `subagent_type` = runtime name, for example `openhands` or `feynman`
- `description` = delegated task description
- `status` = `in_progress | completed | failed`

This avoids inventing a second parallel progress UI.

### Suggested TypeScript delta

Extend the `Subtask` type only if needed, for example with:

```ts
runtime?: "subagent" | "openhands" | "feynman";
```

If the current `subagent_type` string is enough, do not expand the model yet.

## Phase 6: Hardening

### Goal

Make the integration safe and operable.

### Hardening tasks

- reject unsafe `seed_paths`
- enforce timeouts per runtime
- kill orphaned child processes
- cap artifact listing length
- truncate noisy stdout/stderr in returned summaries
- make command-not-found errors actionable
- document required host installations

### Suggested documentation updates

- `README.md`
- `backend/CLAUDE.md`
- `backend/docs/CONFIGURATION.md`

## File-by-File Change Summary

### New files

- `backend/packages/harness/deerflow/tools/delegated_runtime_support.py`
- `backend/packages/harness/deerflow/config/feynman_config.py`
- `backend/packages/harness/deerflow/tools/builtins/invoke_feynman_tool.py`
- `backend/tests/test_delegated_runtime_support.py`
- `backend/tests/test_invoke_feynman_tool.py`
- `skills/custom/delegated-runtime-routing/SKILL.md`

### Modified files

- `config.example.yaml`
- `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py`
- `backend/packages/harness/deerflow/tools/builtins/__init__.py`
- `backend/packages/harness/deerflow/tools/tools.py`
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
- `backend/tests/test_invoke_acp_agent_tool.py`
- `frontend/src/core/threads/hooks.ts`
- `frontend/src/components/workspace/messages/message-list.tsx`
- `frontend/src/core/tasks/types.ts`
- `README.md`
- `backend/CLAUDE.md`

## Delivery Slices

### Slice A: Shared helper + OpenHands ACP hardening

Ship first because:

- DeerFlow already has ACP infrastructure
- the code surface is smaller
- it proves the delegated-runtime helper pattern

### Slice B: Feynman runtime tool

Ship second because:

- it adds a new execution surface
- it benefits from the helper layer built in Slice A

### Slice C: routing skill + frontend event support

Ship third because:

- it improves runtime selection quality
- it makes progress visible

### Slice D: optional custom-agent packaging

Ship last because it is UX packaging, not core runtime integration.

## Acceptance Checklist

- `OpenHands` can be invoked from DeerFlow through `invoke_acp_agent`.
- DeerFlow can seed files into ACP workspace before OpenHands starts.
- `Feynman` can be invoked from DeerFlow through a first-class tool.
- DeerFlow can read normalized artifacts from both runtimes.
- delegated runtime progress is visible in the existing stream UI.
- the lead agent has explicit routing guidance for when to use each runtime.

## References

- Architecture doc: `docs/plans/2026-04-19-openhands-feynman-solution-architecture.md`
- OpenHands ACP docs: <https://docs.openhands.dev/openhands/usage/run-openhands/acp>
- OpenHands command reference: <https://docs.openhands.dev/openhands/usage/cli/command-reference>
- Feynman README: <https://raw.githubusercontent.com/getcompanion-ai/feynman/main/README.md>
