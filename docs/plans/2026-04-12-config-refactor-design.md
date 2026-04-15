# Design: Eliminate Global Mutable State in Configuration System

> Implements [#1811](https://github.com/bytedance/deer-flow/issues/1811) · Tracked in [#2151](https://github.com/bytedance/deer-flow/issues/2151)

## Problem

`deerflow/config/` has three structural issues:

1. **Dual source of truth** — each sub-config exists both as an `AppConfig` field and a module-level global (e.g. `_memory_config`). Consumers don't know which to trust.
2. **Side-effect coupling** — `AppConfig.from_file()` silently mutates 8 sub-module globals via `load_*_from_dict()` calls.
3. **Incomplete isolation** — `ContextVar` only scopes `AppConfig`, not the 8 sub-config globals.

## Design Principle

**Config is a value object, not live shared state.** Constructed once, immutable, no reload. New config = new object + rebuild agent.

## Solution

### 1. Frozen AppConfig (full tree)

All config models set `frozen=True`. No mutation after construction.

```python
class MemoryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    memory: MemoryConfig
    title: TitleConfig
    ...
```

Changes use copy-on-write: `config.model_copy(update={...})`.

### 2. Pure `from_file()`

`AppConfig.from_file()` becomes a pure function — returns a frozen object, no side effects. All `load_*_from_dict()` calls removed.

### 3. Delete sub-module globals

Every sub-config module's global state is deleted:

| Delete | Files |
|--------|-------|
| `_memory_config`, `get_memory_config()`, `set_memory_config()`, `load_memory_config_from_dict()` | `memory_config.py` |
| `_title_config`, `get_title_config()`, `set_title_config()`, `load_title_config_from_dict()` | `title_config.py` |
| Same pattern | `summarization_config.py`, `subagents_config.py`, `guardrails_config.py`, `tool_search_config.py`, `checkpointer_config.py`, `stream_bridge_config.py`, `acp_config.py` |
| `_extensions_config`, `reload_extensions_config()`, `reset_extensions_config()`, `set_extensions_config()` | `extensions_config.py` |
| `reload_app_config()`, `reset_app_config()`, `set_app_config()`, mtime detection, `push/pop_current_app_config()` | `app_config.py` |

Consumers migrate from `get_memory_config()` → `get_app_config().memory`.

### 4. Propagation

#### Agent path: `Runtime[DeerFlowContext]`

LangGraph's official DI mechanism. Context is injected per-invocation, type-safe.

```python
@dataclass(frozen=True)
class DeerFlowContext:
    app_config: AppConfig
    thread_id: str
    agent_name: str | None = None
```

**Fields:**

| Field | Type | Source | Mutability |
|-------|------|--------|-----------|
| `app_config` | `AppConfig` | ContextVar (`get_app_config()`) | Immutable per-run |
| `thread_id` | `str` | Caller-provided | Immutable per-run |
| `agent_name` | `str \| None` | Caller-provided (bootstrap only) | Immutable per-run |

**Not in context:** `sandbox_id` is mutable runtime state (lazy-acquired mid-execution). It flows through `ThreadState.sandbox` (state channel), not context. The 3 existing `runtime.context["sandbox_id"] = ...` writes in `sandbox/tools.py` are removed; `SandboxMiddleware.after_agent` reads from `state["sandbox"]` only.

**Construction per entry point (Gateway is primary):**

```python
# Gateway runtime (worker.py) — primary path
context = DeerFlowContext(app_config=get_app_config(), thread_id=thread_id)
agent.astream(input, config=config, context=context)

# DeerFlowClient (client.py)
context = DeerFlowContext(app_config=self._app_config, thread_id=thread_id)
agent.stream(input, config=config, context=context)

# LangGraph Server — legacy path, context=None, fallback via resolve_context()
```

**Access in middleware/tools:**

```python
from deerflow.config.deer_flow_context import DeerFlowContext, resolve_context

# Middleware
def before_model(self, state, runtime: Runtime[DeerFlowContext]):
    ctx = resolve_context(runtime)
    ctx.app_config.title     # typed
    ctx.thread_id             # typed

# Tool
@tool
def my_tool(runtime: ToolRuntime[DeerFlowContext]) -> str:
    ctx = resolve_context(runtime)
    ctx.app_config.memory    # typed
```

`resolve_context()` returns `runtime.context` directly when it's already a `DeerFlowContext` (Gateway/Client paths). For legacy LangGraph Server path (context is None), it falls back to constructing from ContextVar + `configurable`.

Why `Runtime` over `RunnableConfig.configurable`:
- `Runtime` is LangGraph's official DI, not a private dict hack
- Generic type parameter (`Runtime[DeerFlowContext]`) gives type safety
- `RunnableConfig` is for framework internals (tags, callbacks), not user dependencies

#### Non-agent path: ContextVar

Gateway API routers use `get_app_config()` backed by a single ContextVar. This is appropriate — Gateway doesn't run through the LangGraph execution graph.

### 5. No reload

Config lifecycle is simple:

```
Process start → from_file() → set ContextVar → run
                                                 ↓
                               Gateway API changed file?
                                                 ↓
                               from_file() → new frozen config
                               → set ContextVar → rebuild agent
```

- Edit `config.yaml` → restart process
- Gateway updates MCP/Skills → construct new config + rebuild agent
- No mtime detection, no `reload_*()`, no auto-refresh

### 6. Structure vs runtime config

| Type | Example | Reload behavior |
|------|---------|----------------|
| Structural (agent composition) | model, tools, middleware chain | Requires agent rebuild |
| Runtime (execution behavior) | `memory.enabled`, `title.max_words` | Next invocation picks up new config automatically via `Runtime` |

Middleware reads config from `Runtime` at execution time (not `__init__` capture), so runtime config changes take effect without agent rebuild.

## What doesn't change

- `config.yaml` schema
- `extensions_config.json` loading
- External API behavior (Gateway, DeerFlowClient)

## Migration scope

- 50+ call sites: `get_*_config()` → `get_app_config().xxx`
- Middleware: `__init__` capture → `Runtime[DeerFlowContext]` read
- Tools: global getters → `ToolRuntime[DeerFlowContext]`
- Tests: `reset_*_config()` → construct frozen config directly
- Gateway update flow: reload → construct new config + rebuild agent
- Dependency: upgrade langgraph >= 1.1.5 for `Runtime` support
