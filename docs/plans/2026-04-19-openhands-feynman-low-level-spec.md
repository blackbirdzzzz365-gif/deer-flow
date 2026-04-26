# OpenHands + Feynman Low-Level Implementation Spec

## Status

- Date: `2026-04-21`
- Status: dev-ready handoff spec
- Companion docs:
  - `docs/plans/2026-04-19-openhands-feynman-solution-architecture.md`
  - `docs/plans/2026-04-19-openhands-feynman-implementation-detailed.md`
- Upstream contract freeze used by this spec:
  - `OpenHands CLI`: ACP mode documented at `docs.openhands.dev` on `2026-04-21`
  - `Feynman`: CLI workflows documented in upstream README on `2026-04-21`

## Purpose

The two existing docs are sufficient to choose the architecture, but they still leave too much room for implementation drift. This document removes the remaining ambiguity.

This spec freezes:

1. the exact repo files that must change
2. the exact config and runtime contracts
3. the event payloads used by backend and frontend
4. the production packaging strategy
5. the test matrix and merge order

This is the handoff document the implementing engineer should follow.

## Decisions Frozen By This Spec

### 1. Do not install the runtimes on the production host only

`invoke_acp_agent` and the future `invoke_feynman` tool spawn subprocesses inside the DeerFlow backend container, not on the host. Therefore:

- `OpenHands` and `Feynman` must be available on `PATH` inside the backend image
- production deploy must not depend on a host-only `openhands` or `feynman` install
- `scripts/deploy_production.sh` may validate runtime presence, but it is not the primary installation surface

### 2. OpenHands runs through ACP, but its execution runtime is `process`

`OpenHands` is still integrated through `invoke_acp_agent`, but DeerFlow must configure the OpenHands subprocess with:

- `args: ["acp", "--always-approve", "--override-with-envs"]`
- environment-based model configuration
- `RUNTIME=process`

Reason:

- DeerFlow already runs inside a container and exposes a Docker socket for its own sandbox flow
- forcing OpenHands to start an additional nested Docker runtime would create avoidable path and mount translation problems for `/mnt/acp-workspace`
- `process` runtime lets OpenHands operate directly against the ACP workspace that DeerFlow already manages

### 3. OpenHands model settings are independent from DeerFlow `models:`

Do not infer OpenHands LLM configuration from DeerFlow's `models:` section.

Instead, `config.template.yaml` and `config.example.yaml` must declare env-backed values for the OpenHands subprocess itself, for example:

- `OPENHANDS_LLM_MODEL`
- `OPENHANDS_LLM_API_KEY`
- `OPENHANDS_LLM_BASE_URL`
- optional `OPENHANDS_LLM_CUSTOM_LLM_PROVIDER`

This avoids binding DeerFlow's internal model alias system to OpenHands' own runtime settings.

### 4. Feynman stays a first-class DeerFlow tool, not ACP

Feynman V1 is implemented as a built-in tool named `invoke_feynman`.

It runs in a delegated work directory under DeerFlow's normal thread workspace and uses the upstream CLI workflows that exist today:

- default `feynman "<prompt>"`
- `deepresearch`
- `lit`
- `review`
- `audit`
- `compare`
- `draft`

V1 does not expose:

- `watch`
- `replicate`
- `autoresearch`

Those workflows are either long-running, more autonomous than DeerFlow needs, or require a separate lifecycle beyond the scope of this integration.

### 5. Frontend delegated-runtime cards are keyed by `tool_call_id`, not `run_id`

`run_id` is created only after the backend prepares a runtime workspace. The frontend already knows the LangChain `tool_call_id` as soon as the AI message is streamed.

Therefore:

- the UI anchor key is `tool_call_id`
- backend custom events must include both `tool_call_id` and `run_id`
- `run_id` is still used for filesystem locations and artifact manifests

This decision prevents race conditions where the UI cannot render a card until after the first custom event arrives.

## Exact File-Level Change Set

### Files to add

| Path | Purpose |
| --- | --- |
| `backend/packages/harness/deerflow/tools/delegated_runtime_support.py` | Shared run directory, manifest, artifact, and custom-event helpers |
| `backend/packages/harness/deerflow/config/feynman_config.py` | Pydantic config model + singleton loader for Feynman runtime |
| `backend/packages/harness/deerflow/tools/builtins/invoke_feynman_tool.py` | First-class Feynman CLI tool |
| `backend/tests/test_delegated_runtime_support.py` | Helper-layer tests |
| `backend/tests/test_invoke_feynman_tool.py` | Feynman tool tests |
| `skills/custom/delegated-runtime-routing/SKILL.md` | Repo-local routing guidance for lead agent |

### Files to change

| Path | Required change |
| --- | --- |
| `backend/packages/harness/deerflow/config/app_config.py` | Load and expose `feynman` config |
| `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py` | Add seeding, artifact discovery, OpenHands prompt contract, and runtime events |
| `backend/packages/harness/deerflow/tools/tools.py` | Register `invoke_feynman` when enabled |
| `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` | Add explicit routing rules for OpenHands vs Feynman vs direct tools |
| `backend/tests/test_app_config_reload.py` | Verify Feynman config resets correctly on reload |
| `backend/tests/test_invoke_acp_agent_tool.py` | Extend ACP tests for OpenHands flow |
| `backend/tests/test_lead_agent_prompt.py` | Assert routing guidance appears when enabled |
| `config.example.yaml` | Document user-facing config for both runtimes |
| `backend/Dockerfile` | Bake OpenHands and Feynman into the backend image |
| `docker-compose.production.yml` | Persist OpenHands/Feynman home directories into containers |
| `deploy/backup-blackbird/config.template.yaml` | Production config for OpenHands ACP and Feynman tool |
| `deploy/backup-blackbird/app.env.example` | Production env placeholders for both runtimes |
| `scripts/deploy_production.sh` | Validate runtime binaries exist after image update |
| `frontend/src/core/tasks/types.ts` | Extend `Subtask` for delegated runtimes |
| `frontend/src/core/tasks/context.tsx` | Fix state updates so delegated-runtime events always rerender |
| `frontend/src/core/threads/hooks.ts` | Map delegated-runtime custom events into subtask state |
| `frontend/src/components/workspace/messages/message-list.tsx` | Render runtime cards for `invoke_feynman` and `invoke_acp_agent` tool calls |
| `frontend/src/components/workspace/messages/subtask-card.tsx` | Display runtime progress text and artifact info when no `AIMessage` exists |

## Backend Specification

### 1. Shared delegated-runtime helper

Create `backend/packages/harness/deerflow/tools/delegated_runtime_support.py` with these public types and helpers.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(slots=True)
class DelegatedRunPaths:
    runtime: str
    run_id: str
    slug: str
    thread_id: str
    host_dir: Path
    virtual_dir: str
    inputs_dir: Path
    deerflow_dir: Path
    task_file: Path
    result_file: Path
    log_file: Path
    manifest_file: Path


def create_delegated_run(
    *,
    runtime: Literal["feynman", "openhands"],
    thread_id: str,
    description: str,
    location: Literal["workspace", "acp"],
) -> DelegatedRunPaths: ...


def copy_seed_paths(
    *,
    thread_id: str,
    seed_paths: list[str],
    destination_dir: Path,
) -> list[str]: ...


def write_task_brief(
    *,
    paths: DelegatedRunPaths,
    description: str,
    prompt: str,
    metadata: dict[str, Any],
) -> None: ...


def discover_artifacts(
    *,
    root_dir: Path,
    virtual_root: str,
    patterns: list[str],
    max_artifacts: int,
) -> list[str]: ...


def write_result_file(
    *,
    paths: DelegatedRunPaths,
    status: Literal["completed", "failed", "timed_out"],
    summary: str | None,
    artifacts: list[str],
    extra: dict[str, Any] | None = None,
) -> None: ...


def emit_runtime_event(
    *,
    event_type: Literal[
        "delegated_runtime_started",
        "delegated_runtime_progress",
        "delegated_runtime_completed",
        "delegated_runtime_failed",
    ],
    tool_call_id: str,
    runtime: str,
    run_id: str,
    description: str,
    phase: str,
    message: str,
    prompt: str | None = None,
    virtual_dir: str | None = None,
    result_file: str | None = None,
    artifacts: list[str] | None = None,
    error: str | None = None,
) -> None: ...
```

### 1.1 Directory policy

`create_delegated_run()` must use deterministic locations:

- Feynman:
  - host: `backend/.deer-flow/threads/{thread_id}/user-data/workspace/.delegated/feynman/{run_id}-{slug}/`
  - virtual: `/mnt/user-data/workspace/.delegated/feynman/{run_id}-{slug}/`
- OpenHands:
  - host: `backend/.deer-flow/threads/{thread_id}/acp-workspace/`
  - virtual: `/mnt/acp-workspace`
  - no nested run directory at the ACP root level
  - per-run DeerFlow outputs go under `/mnt/acp-workspace/deerflow/{run_id}/`

For OpenHands, `DelegatedRunPaths.deerflow_dir` must be:

- host: `{acp-workspace}/deerflow/{run_id}/`
- virtual: `/mnt/acp-workspace/deerflow/{run_id}/`

### 1.2 Seed path safety

`copy_seed_paths()` must:

- accept only paths under `/mnt/user-data/`
- resolve them with `get_paths().resolve_virtual_path(thread_id, virtual_path)`
- reject traversal attempts
- copy files or directories into a runtime-local `inputs/` folder
- return the copied paths in runtime-local virtual form

Explicitly reject:

- `/mnt/acp-workspace/*`
- `/mnt/skills/*`
- arbitrary host paths

### 1.3 Normalized result file

Both runtimes must end by writing `deerflow-result.json`.

Frozen JSON shape:

```json
{
  "runtime": "feynman",
  "run_id": "feynman-20260421-120102-deep-lit",
  "status": "completed",
  "description": "Deep literature review",
  "virtual_dir": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit",
  "task_file": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit/task.md",
  "result_file": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit/deerflow-result.json",
  "log_file": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit/run.log",
  "summary": "Short DeerFlow-facing summary",
  "artifacts": [
    "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit/outputs/report.md"
  ],
  "metadata": {
    "workflow": "lit",
    "seed_paths": [
      "/mnt/user-data/uploads/papers/request.txt"
    ]
  },
  "error": null
}
```

Rules:

- `summary` is always DeerFlow-authored, not raw subprocess stdout
- `artifacts` contains virtual paths only
- `metadata` is runtime-specific
- `error` is non-null only on failed or timed-out runs

## 2. OpenHands ACP implementation

### 2.1 Input schema

Update `_InvokeACPAgentInput` in `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py` to:

```python
class _InvokeACPAgentInput(BaseModel):
    agent: str = Field(description="Name of the ACP agent to invoke")
    prompt: str = Field(description="Task prompt for the ACP agent")
    description: str = Field(
        default="",
        description="Short UI label for the delegated run. If omitted, the backend derives one from the prompt.",
    )
    seed_paths: list[str] = Field(
        default_factory=list,
        description="Optional /mnt/user-data files or directories to copy into ACP inputs before launch",
    )
    expected_outputs: list[str] = Field(
        default_factory=list,
        description="Optional relative output hints for the agent, such as summary.md or patch.diff",
    )
```

Do not make `description` required in code, but the lead-agent prompt and routing skill must instruct the model to always provide it.

### 2.2 Runtime behavior

`build_invoke_acp_agent_tool()` must:

1. determine `thread_id`
2. create OpenHands delegated paths through `create_delegated_run(..., runtime="openhands", location="acp")`
3. copy `seed_paths` into `{acp-workspace}/inputs/{run_id}/`
4. write `task.md`
5. emit `delegated_runtime_started`
6. augment the effective prompt
7. spawn the ACP session
8. discover outputs under `/mnt/acp-workspace/deerflow/{run_id}/`
9. write normalized `deerflow-result.json`
10. emit `delegated_runtime_completed` or `delegated_runtime_failed`

### 2.3 Prompt augmentation rules

When `agent != "openhands"`, keep the current generic ACP behavior plus seeding support.

When `agent == "openhands"`, append this contract to the effective prompt:

```text
DeerFlow runtime contract:
- Read task context from ./inputs/<run_id>/ when present.
- Write all DeerFlow deliverables under ./deerflow/<run_id>/ .
- Required file: deerflow/<run_id>/summary.md
- Required file: deerflow/<run_id>/artifacts.json
- Optional file for code changes: deerflow/<run_id>/patch.diff
- Optional screenshots: deerflow/<run_id>/screenshots/*
- Do not write outside ./deerflow/<run_id>/ except for temporary work files.
```

The code must not depend on OpenHands perfectly following this contract. After completion, DeerFlow still discovers artifacts itself and writes the normalized result file.

### 2.4 OpenHands config in YAML

`config.example.yaml` and `deploy/backup-blackbird/config.template.yaml` must expose an `acp_agents.openhands` entry like:

```yaml
acp_agents:
  openhands:
    command: openhands
    args: ["acp", "--always-approve", "--override-with-envs"]
    description: OpenHands for isolated coding, browser debugging, and patch generation
    auto_approve_permissions: true
    env:
      RUNTIME: process
      LLM_MODEL: $OPENHANDS_LLM_MODEL
      LLM_API_KEY: $OPENHANDS_LLM_API_KEY
      LLM_BASE_URL: $OPENHANDS_LLM_BASE_URL
      LLM_CUSTOM_LLM_PROVIDER: $OPENHANDS_LLM_CUSTOM_LLM_PROVIDER
```

Notes:

- keep `RUNTIME=process`
- keep `--override-with-envs`
- do not use DeerFlow's internal model aliases as the literal OpenHands model string

### 2.5 OpenHands return string

The tool return string must be concise and structured:

```text
OpenHands completed.

Summary:
<summary text>

Artifacts:
- /mnt/acp-workspace/deerflow/<run_id>/summary.md
- /mnt/acp-workspace/deerflow/<run_id>/artifacts.json
- /mnt/acp-workspace/deerflow/<run_id>/patch.diff
```

On failure:

```text
OpenHands failed.

Reason:
<error text>

Result file:
- /mnt/acp-workspace/deerflow/<run_id>/deerflow-result.json
```

## 3. Feynman tool implementation

### 3.1 Config model

Add `backend/packages/harness/deerflow/config/feynman_config.py` with this frozen model shape:

```python
from collections.abc import Mapping

from pydantic import BaseModel, Field


class FeynmanConfig(BaseModel):
    enabled: bool = Field(default=False)
    command: str = Field(default="feynman")
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=1800)
    max_artifacts: int = Field(default=50)
    max_log_chars: int = Field(default=20000)
    workflows: list[str] = Field(
        default_factory=lambda: ["research", "deepresearch", "lit", "review", "audit", "compare", "draft"]
    )
    artifact_globs: list[str] = Field(
        default_factory=lambda: [
            "outputs/**/*",
            "papers/**/*",
            "notes/**/*",
            "*.md",
            "*.json",
        ]
    )


def get_feynman_config() -> FeynmanConfig: ...
def load_feynman_config_from_dict(config_dict: Mapping[str, object] | None) -> None: ...
```

Pattern requirements:

- follow the same singleton-loader style used by `acp_config.py`
- default `enabled=False`
- loading `None` or `{}` must reset to defaults

### 3.2 `AppConfig` changes

In `backend/packages/harness/deerflow/config/app_config.py`:

1. import `FeynmanConfig` and `load_feynman_config_from_dict`
2. add field:

```python
feynman: FeynmanConfig = Field(
    default_factory=FeynmanConfig,
    description="Feynman delegated runtime configuration",
)
```

3. in `from_file()`, always call:

```python
load_feynman_config_from_dict(config_data.get("feynman") or {})
```

This must happen even when the section is absent, exactly like the ACP reset behavior.

### 3.3 Tool registration

In `backend/packages/harness/deerflow/tools/tools.py`:

- import `get_feynman_config`
- import `build_invoke_feynman_tool`
- append the tool only when `config.feynman.enabled` is true

The tool is dynamic like `invoke_acp_agent`; it does not need an export from `backend/packages/harness/deerflow/tools/builtins/__init__.py`.

### 3.4 Tool input schema

Create `backend/packages/harness/deerflow/tools/builtins/invoke_feynman_tool.py` with:

```python
class _InvokeFeynmanInput(BaseModel):
    description: str = Field(description="Short UI label for the delegated run")
    prompt: str = Field(description="Research task for Feynman")
    workflow: str = Field(
        default="research",
        description="One of research, deepresearch, lit, review, audit, compare, draft",
    )
    seed_paths: list[str] = Field(
        default_factory=list,
        description="Optional /mnt/user-data files or directories to copy into ./context before launch",
    )
    expected_artifacts: list[str] = Field(
        default_factory=list,
        description="Optional relative artifact hints, such as outputs/report.md",
    )
```

### 3.5 Command mapping

Frozen workflow mapping for V1:

| Tool workflow | CLI command |
| --- | --- |
| `research` | `feynman "<prompt>"` |
| `deepresearch` | `feynman deepresearch "<prompt>"` |
| `lit` | `feynman lit "<prompt>"` |
| `review` | `feynman review "<prompt>"` |
| `audit` | `feynman audit "<prompt>"` |
| `compare` | `feynman compare "<prompt>"` |
| `draft` | `feynman draft "<prompt>"` |

Reject any workflow not present in `config.feynman.workflows` before starting the subprocess.

### 3.6 Runtime behavior

`build_invoke_feynman_tool()` must:

1. resolve `thread_id`
2. create delegated run paths under `workspace/.delegated/feynman`
3. copy `seed_paths` into `context/`
4. write `task.md`
5. emit `delegated_runtime_started`
6. start the subprocess with:
   - `cwd=run_dir`
   - merged env from `os.environ` and `config.feynman.env`
   - stdout and stderr captured into `run.log`
7. stream coarse progress events
8. apply timeout from `config.feynman.timeout_seconds`
9. collect artifacts with `artifact_globs`
10. write normalized `deerflow-result.json`
11. return a short DeerFlow-facing summary

Implementation details:

- use `asyncio.create_subprocess_exec`
- do not use shell mode
- write `stdout` and `stderr` into the same log file in append order
- on timeout, terminate the process, then kill if needed, then write a timed-out result file

### 3.7 Feynman config in YAML

Add this section to `config.example.yaml` and `deploy/backup-blackbird/config.template.yaml`:

```yaml
feynman:
  enabled: true
  command: feynman
  args: []
  timeout_seconds: 1800
  max_artifacts: 50
  max_log_chars: 20000
  workflows: ["research", "deepresearch", "lit", "review", "audit", "compare", "draft"]
  artifact_globs:
    - outputs/**/*
    - papers/**/*
    - notes/**/*
    - "*.md"
    - "*.json"
  env:
    FEYNMAN_MODEL: $FEYNMAN_MODEL
```

Do not add per-thread behavior into config; per-thread routing stays in tool runtime logic.

### 3.8 Feynman return string

The tool return string must use this shape:

```text
Feynman completed.

Summary:
<summary text>

Artifacts:
- /mnt/user-data/workspace/.delegated/feynman/<run_id>/outputs/report.md
- /mnt/user-data/workspace/.delegated/feynman/<run_id>/notes/summary.md
```

On failure:

```text
Feynman failed.

Reason:
<error text>

Result file:
- /mnt/user-data/workspace/.delegated/feynman/<run_id>/deerflow-result.json
```

## 4. Lead-agent routing specification

### 4.1 Prompt changes

Update `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` in the existing ACP section plus one new delegated-runtime section.

The new routing rules must say:

- prefer direct DeerFlow tools for simple local read/write/bash work
- use `task()` for parallel bounded exploration
- use `invoke_feynman` for evidence-heavy research, compare, audit, and cited synthesis
- use `invoke_acp_agent(agent="openhands", ...)` for code execution, browser debugging, repo-heavy tasks, and patch generation
- after delegated completion, inspect artifacts before replying

Do not make this guidance brand-only. The wording must preserve capability-first routing.

### 4.2 Repo-local skill

Create `skills/custom/delegated-runtime-routing/SKILL.md`.

Minimal contents:

- when to use direct tools
- when to use `task`
- when to use OpenHands
- when to use Feynman
- required argument patterns:
  - `description`
  - `prompt`
  - `seed_paths`
- post-run behavior:
  - inspect `deerflow-result.json`
  - read the main summary artifact
  - optionally copy user-facing files into `/mnt/user-data/outputs`

This skill is required in V1 because routing is likely to evolve faster than the hardcoded prompt.

## 5. Custom event contract

Backend and frontend must share this exact payload family.

### 5.1 Started event

```json
{
  "type": "delegated_runtime_started",
  "tool_call_id": "call_abc123",
  "run_id": "feynman-20260421-120102-deep-lit",
  "runtime": "feynman",
  "description": "Deep literature review",
  "prompt": "Compare the latest..."
}
```

### 5.2 Progress event

```json
{
  "type": "delegated_runtime_progress",
  "tool_call_id": "call_abc123",
  "run_id": "feynman-20260421-120102-deep-lit",
  "runtime": "feynman",
  "description": "Deep literature review",
  "phase": "invoke",
  "message": "Feynman process started",
  "virtual_dir": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit"
}
```

Allowed `phase` values:

- `prepare`
- `invoke`
- `collect`
- `complete`

### 5.3 Completed event

```json
{
  "type": "delegated_runtime_completed",
  "tool_call_id": "call_abc123",
  "run_id": "feynman-20260421-120102-deep-lit",
  "runtime": "feynman",
  "description": "Deep literature review",
  "phase": "complete",
  "message": "Artifacts collected",
  "virtual_dir": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit",
  "result_file": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit/deerflow-result.json",
  "artifacts": [
    "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit/outputs/report.md"
  ]
}
```

### 5.4 Failed event

```json
{
  "type": "delegated_runtime_failed",
  "tool_call_id": "call_abc123",
  "run_id": "feynman-20260421-120102-deep-lit",
  "runtime": "feynman",
  "description": "Deep literature review",
  "phase": "complete",
  "message": "Feynman process exited with code 1",
  "result_file": "/mnt/user-data/workspace/.delegated/feynman/feynman-20260421-120102-deep-lit/deerflow-result.json",
  "error": "exit code 1"
}
```

## 6. Frontend specification

### 6.1 `Subtask` type changes

Update `frontend/src/core/tasks/types.ts` to:

```ts
export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type: string;
  description: string;
  prompt: string;
  latestMessage?: AIMessage;
  latestText?: string;
  result?: string;
  error?: string;
  runtime?: "subagent" | "openhands" | "feynman" | "acp";
  runId?: string;
  artifacts?: string[];
  resultFile?: string;
}
```

### 6.2 Fix `useUpdateSubtask`

`frontend/src/core/tasks/context.tsx` currently mutates the task map in place and only triggers `setTasks()` when `latestMessage` exists.

This must be changed before delegated-runtime events are added.

Frozen implementation:

```ts
const updateSubtask = useCallback((task: Partial<Subtask> & { id: string }) => {
  setTasks((prev) => ({
    ...prev,
    [task.id]: {
      ...prev[task.id],
      ...task,
    } as Subtask,
  }));
}, [setTasks]);
```

Do not keep the current in-place mutation logic.

### 6.3 `hooks.ts` event mapping

In `frontend/src/core/threads/hooks.ts`, `onCustomEvent()` must handle the four delegated-runtime event types.

State mapping:

- `id` = `tool_call_id`
- `runtime` = `runtime` for Feynman, `openhands` for OpenHands, otherwise `acp`
- `runId` = `run_id`
- `description` = event `description`
- `prompt` = event `prompt` when present, otherwise preserve existing
- `latestText` = event `message`
- `resultFile` = event `result_file`
- `artifacts` = event `artifacts`

Status mapping:

- started -> `in_progress`
- progress -> `in_progress`
- completed -> `completed`
- failed -> `failed`

### 6.4 `message-list.tsx`

The UI must render runtime cards whenever an AI message contains either:

- `invoke_feynman`
- `invoke_acp_agent`

Implementation rules:

1. scan `message.tool_calls` in the generic assistant groups
2. when `toolCall.name === "invoke_feynman"`, create/update a subtask with:
   - `id = toolCall.id`
   - `runtime = "feynman"`
   - `description = toolCall.args.description`
   - `prompt = toolCall.args.prompt`
3. when `toolCall.name === "invoke_acp_agent"`, create/update a subtask with:
   - `id = toolCall.id`
   - `runtime = toolCall.args.agent === "openhands" ? "openhands" : "acp"`
   - `description = toolCall.args.description || \`ACP: ${toolCall.args.agent}\``
   - `prompt = toolCall.args.prompt`
4. render `SubtaskCard` immediately below that assistant message group for each delegated-runtime tool call

This is required. Custom events alone are not enough because the current `MessageList` only renders cards for the `task` tool.

### 6.5 `subtask-card.tsx`

Add fallback rendering rules:

- when `latestMessage` exists, keep the current subagent display
- when `latestText` exists, display that as progress text
- when `artifacts` exists and status is completed, render a short artifact list under the result section
- when `resultFile` exists and status is failed, show it as the canonical debugging path

No locale work is required in V1. Reuse existing generic status labels.

## 7. Container and production packaging

### 7.1 Backend image

Modify `backend/Dockerfile`.

Frozen strategy:

1. install OpenHands and Feynman in the `builder` stage
2. make the binaries available in `dev`
3. copy the installed runtime directories into the final runtime image

Required Dockerfile additions:

- build args:
  - `ARG OPENHANDS_VERSION=1.14.0`
  - `ARG FEYNMAN_VERSION=0.2.40`
- install OpenHands with `uv tool install --python 3.12 "openhands==${OPENHANDS_VERSION}"`
- install Feynman using its official installer at build time
- fail the build if `openhands` or `feynman` are not executable after install
- ensure `/root/.local/bin` is on `PATH`

The runtime stage must copy any runtime state needed by the installed CLIs, not just the launcher symlink. At minimum copy:

- `/root/.local`
- any Feynman runtime home created during install, if distinct from `/root/.local`

### 7.2 Production mounts

Update `docker-compose.production.yml` so both `gateway` and `langgraph` mount persistent runtime homes:

- `${DEER_FLOW_HOME}/openhands-home:/root/.openhands`
- `${DEER_FLOW_HOME}/feynman-home:/root/.feynman`

Reason:

- persist OpenHands optional settings/logs
- persist Feynman local state between deploys
- keep runtime-specific state inside DeerFlow's managed home, not elsewhere on the host

### 7.3 Production env template

Extend `deploy/backup-blackbird/app.env.example` with:

```dotenv
OPENHANDS_LLM_MODEL=replace-me
OPENHANDS_LLM_API_KEY=replace-me
OPENHANDS_LLM_BASE_URL=replace-me
OPENHANDS_LLM_CUSTOM_LLM_PROVIDER=openai

FEYNMAN_MODEL=replace-me
# Standard provider envs consumed by Feynman/its agent stack can also be set here:
# OPENAI_API_KEY=
# OPENROUTER_API_KEY=
# ANTHROPIC_API_KEY=
# GEMINI_API_KEY=
# XAI_API_KEY=
```

Do not put `OPENHANDS_VERSION` or `FEYNMAN_VERSION` into runtime `.env`. Those version pins belong in `backend/Dockerfile` defaults and, if needed later, the image-build workflow.

### 7.4 Deploy script validation

`scripts/deploy_production.sh` must validate the new image actually contains the runtimes after `docker compose up -d`.

Minimal validation:

- `docker compose exec -T langgraph openhands --help >/dev/null`
- `docker compose exec -T langgraph feynman --help >/dev/null`

If either command fails, the deploy script must exit non-zero before writing the new production state file.

Do not move installation logic into `deploy_production.sh`.

## 8. Test matrix

### 8.1 Helper tests

`backend/tests/test_delegated_runtime_support.py`

Required cases:

- run ID slug normalization
- Feynman workspace path creation
- OpenHands ACP path creation
- seed path copy for file and directory inputs
- rejection of traversal and non-`/mnt/user-data` paths
- artifact discovery returns only virtual paths
- result file structure is deterministic

### 8.2 ACP tests

Extend `backend/tests/test_invoke_acp_agent_tool.py`.

Required cases:

- `seed_paths` are copied into ACP inputs
- OpenHands prompt contract is appended
- delegated runtime events are emitted in the right order
- discovered OpenHands artifact paths are returned
- invalid `seed_paths` are rejected
- non-OpenHands ACP agents keep generic behavior

### 8.3 App config reload tests

Extend `backend/tests/test_app_config_reload.py`.

Required cases:

- enabling Feynman through config surfaces `config.feynman.enabled is True`
- removing the `feynman:` section resets the singleton-backed config to disabled defaults

### 8.4 Feynman tests

`backend/tests/test_invoke_feynman_tool.py`

Required cases:

- disabled config rejects tool loading
- invalid workflow rejected before subprocess start
- delegated run directory created correctly
- seed files copied into `context/`
- subprocess success writes normalized result file
- subprocess timeout writes timed-out result file
- discovered artifacts are returned as virtual paths
- delegated runtime events are emitted in the right order
- command-not-found returns actionable error text

### 8.5 Prompt tests

Extend `backend/tests/test_lead_agent_prompt.py`.

Required cases:

- routing guidance mentions Feynman when enabled
- routing guidance mentions ACP/OpenHands when ACP agents include `openhands`
- guidance does not tell the model to pass `/mnt/user-data` paths directly into ACP prompts

### 8.6 Frontend tests

If the repo already has frontend test coverage in this area, add focused tests. If not, at minimum add runtime mapping coverage wherever the current frontend test strategy lives.

Required behavioral assertions:

- delegated-runtime events create and update subtask state by `tool_call_id`
- completed events preserve `artifacts`
- failed events preserve `resultFile` and `error`
- `useUpdateSubtask` rerenders on status-only changes

## 9. Implementation order

PR slices must be merged in this order:

1. shared delegated-runtime helper + tests
2. Feynman config + app-config load/reset tests
3. OpenHands ACP enhancement + ACP tests
4. Feynman tool + tests
5. lead prompt + routing skill
6. frontend delegated-runtime rendering
7. backend image + production config + deploy validation

Do not start with the frontend. The frontend depends on the final event contract.

## 10. Definition of done

This integration is only complete when all conditions below are true:

- `invoke_acp_agent(agent="openhands", ...)` can seed `/mnt/user-data` files into ACP workspace
- OpenHands writes or DeerFlow discovers artifacts under `/mnt/acp-workspace/deerflow/{run_id}/`
- `invoke_feynman(...)` runs in `/mnt/user-data/workspace/.delegated/feynman/...`
- both runtimes produce `deerflow-result.json`
- frontend renders runtime progress cards keyed by `tool_call_id`
- backend image contains working `openhands` and `feynman` binaries
- production templates expose the required env variables
- tests for helper, ACP, config reload, and Feynman pass
- one manual smoke test is recorded for each runtime

## 11. Manual smoke tests

Before production deploy, run both:

### OpenHands smoke test

Prompt DeerFlow to:

- call `invoke_acp_agent(agent="openhands", ...)`
- seed one local repo file
- ask for a summary and patch proposal

Verify:

- progress events appear in UI
- `/mnt/acp-workspace/deerflow/{run_id}/summary.md` exists
- `/mnt/acp-workspace/deerflow/{run_id}/deerflow-result.json` exists

### Feynman smoke test

Prompt DeerFlow to:

- call `invoke_feynman(...)`
- seed one uploaded text brief
- run `workflow="lit"` or `workflow="compare"`

Verify:

- progress events appear in UI
- `/mnt/user-data/workspace/.delegated/feynman/{run_id}/deerflow-result.json` exists
- at least one artifact under `outputs/`, `notes/`, or `papers/` is discoverable
