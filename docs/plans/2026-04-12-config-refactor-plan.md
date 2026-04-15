# Config Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate global mutable state in the configuration system — frozen AppConfig, pure `from_file()`, single ContextVar, `Runtime[DeerFlowContext]` propagation.

**Architecture:** All config models become `frozen=True`. `from_file()` becomes a pure function (no side effects). Sub-config module globals are deleted; consumers migrate to `get_app_config().xxx`. Agent execution path uses LangGraph `Runtime[DeerFlowContext]` for typed, per-invocation config access. Gateway path uses a single ContextVar.

**Tech Stack:** Pydantic v2 (`frozen=True`, `model_copy`), Python `contextvars.ContextVar`, LangGraph `Runtime`/`ToolRuntime` (>= 1.1.5)

**Design Spec:** `docs/plans/2026-04-12-config-refactor-design.md`
**Issues:** #2151 (implementation), #1811 (RFC)

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `deerflow/config/context.py` | `DeerFlowContext` frozen dataclass + `init_app_config()` / `get_app_config()` backed by single ContextVar |

### Modified files (config layer)

| File | Change |
|------|--------|
| `deerflow/config/app_config.py` | `frozen=True`, purify `from_file()`, delete mtime/reload/reset/push/pop machinery |
| `deerflow/config/memory_config.py` | `frozen=True`, delete globals (`_memory_config`, `get_memory_config`, `set_memory_config`, `load_memory_config_from_dict`) |
| `deerflow/config/title_config.py` | Same pattern |
| `deerflow/config/summarization_config.py` | Same pattern |
| `deerflow/config/subagents_config.py` | Same pattern |
| `deerflow/config/guardrails_config.py` | Same pattern (also delete `reset_guardrails_config`) |
| `deerflow/config/tool_search_config.py` | Same pattern |
| `deerflow/config/checkpointer_config.py` | Same pattern |
| `deerflow/config/stream_bridge_config.py` | Same pattern |
| `deerflow/config/acp_config.py` | Same pattern |
| `deerflow/config/extensions_config.py` | `frozen=True`, delete globals (`_extensions_config`, `reload_extensions_config`, `reset_extensions_config`, `set_extensions_config`) |
| `deerflow/config/__init__.py` | Update exports — remove deleted getters, add `init_app_config`, `DeerFlowContext` |

### Modified files (consumers — production code)

| File | Change |
|------|--------|
| `deerflow/agents/lead_agent/agent.py` | `get_app_config()` calls stay; `get_summarization_config()` → `get_app_config().summarization` |
| `deerflow/agents/lead_agent/prompt.py` | `get_memory_config()` → `get_app_config().memory`; `get_acp_agents()` → `get_app_config()` based |
| `deerflow/agents/middlewares/memory_middleware.py` | `get_memory_config()` → read from `Runtime` or `get_app_config().memory` |
| `deerflow/agents/middlewares/title_middleware.py` | `get_title_config()` → read from `Runtime` or `get_app_config().title` |
| `deerflow/agents/middlewares/tool_error_handling_middleware.py` | `get_guardrails_config()` → `get_app_config().guardrails` |
| `deerflow/agents/memory/updater.py` | `get_memory_config()` → `get_app_config().memory` |
| `deerflow/agents/memory/queue.py` | `get_memory_config()` → `get_app_config().memory` |
| `deerflow/agents/memory/storage.py` | `get_memory_config()` → `get_app_config().memory` |
| `deerflow/agents/checkpointer/provider.py` | `get_checkpointer_config()` → `get_app_config().checkpointer` |
| `deerflow/runtime/store/provider.py` | `get_checkpointer_config()` → `get_app_config().checkpointer` |
| `deerflow/runtime/stream_bridge/async_provider.py` | `get_stream_bridge_config()` → `get_app_config().stream_bridge` |
| `deerflow/subagents/registry.py` | `get_subagents_app_config()` → `get_app_config().subagents` |
| `deerflow/tools/tools.py` | `get_acp_agents()` → `get_app_config()` based |
| `deerflow/client.py` | Remove `reload_app_config`/`reload_extensions_config` imports and calls; use `init_app_config()` |
| `app/gateway/routers/mcp.py` | `reload_extensions_config()` → construct new config + `init_app_config()` |
| `app/gateway/routers/skills.py` | Same |
| `app/gateway/routers/memory.py` | `get_memory_config()` → `get_app_config().memory` |
| `app/gateway/app.py` | Call `init_app_config()` at startup |

### Modified files (tests)

~100 test locations need updating. Pattern: replace `patch("...get_memory_config", ...)` with `patch("...get_app_config", ...)` returning a frozen AppConfig with the desired sub-config.

---

## Task 1: Freeze all sub-config models

**Files:**
- Modify: `deerflow/config/memory_config.py`
- Modify: `deerflow/config/title_config.py`
- Modify: `deerflow/config/summarization_config.py`
- Modify: `deerflow/config/subagents_config.py`
- Modify: `deerflow/config/guardrails_config.py`
- Modify: `deerflow/config/tool_search_config.py`
- Modify: `deerflow/config/checkpointer_config.py`
- Modify: `deerflow/config/stream_bridge_config.py`
- Modify: `deerflow/config/token_usage_config.py`
- Modify: `deerflow/config/skills_config.py`
- Modify: `deerflow/config/skill_evolution_config.py`
- Modify: `deerflow/config/sandbox_config.py`
- Modify: `deerflow/config/model_config.py`
- Modify: `deerflow/config/tool_config.py`
- Modify: `deerflow/config/agents_config.py`
- Modify: `deerflow/config/extensions_config.py` (McpServerConfig, McpOAuthConfig, SkillStateConfig, ExtensionsConfig)
- Test: `tests/test_config_frozen.py`

- [ ] **Step 1: Write test that all config models are frozen**

```python
# tests/test_config_frozen.py
import pytest
from pydantic import ValidationError

from deerflow.config.memory_config import MemoryConfig
from deerflow.config.title_config import TitleConfig
from deerflow.config.summarization_config import SummarizationConfig
from deerflow.config.subagents_config import SubagentsAppConfig
from deerflow.config.guardrails_config import GuardrailsConfig
from deerflow.config.tool_search_config import ToolSearchConfig
from deerflow.config.checkpointer_config import CheckpointerConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig
from deerflow.config.token_usage_config import TokenUsageConfig
from deerflow.config.skills_config import SkillsConfig
from deerflow.config.skill_evolution_config import SkillEvolutionConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.tool_config import ToolConfig, ToolGroupConfig
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig


@pytest.mark.parametrize("cls,kwargs", [
    (MemoryConfig, {}),
    (TitleConfig, {}),
    (SummarizationConfig, {}),
    (SubagentsAppConfig, {}),
    (GuardrailsConfig, {}),
    (ToolSearchConfig, {}),
    (TokenUsageConfig, {}),
    (SkillsConfig, {}),
    (SkillEvolutionConfig, {}),
    (McpServerConfig, {}),
    (ExtensionsConfig, {}),
])
def test_config_model_is_frozen(cls, kwargs):
    """All config models must be frozen — mutation raises ValidationError."""
    instance = cls(**kwargs)
    first_field = next(iter(cls.model_fields))
    with pytest.raises(ValidationError):
        setattr(instance, first_field, getattr(instance, first_field))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_config_frozen.py -v`
Expected: FAIL — models are not frozen yet

- [ ] **Step 3: Add `frozen=True` to every config model**

Add `model_config = ConfigDict(frozen=True)` (or update existing `ConfigDict`) in each file listed above. For models that already have `ConfigDict(extra="allow")`, change to `ConfigDict(extra="allow", frozen=True)`.

Example for `memory_config.py`:
```python
from pydantic import BaseModel, ConfigDict, Field

class MemoryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    # ... fields unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_config_frozen.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite, fix any tests that mutate config objects**

Run: `cd backend && PYTHONPATH=. uv run pytest -x -v 2>&1 | head -100`

If tests fail because they mutate frozen config objects, fix them using `model_copy(update={...})` or by constructing fresh instances.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(config): make all config models frozen"
```

---

## Task 2: Freeze AppConfig

**Files:**
- Modify: `deerflow/config/app_config.py`
- Test: `tests/test_config_frozen.py` (extend)

- [ ] **Step 1: Add AppConfig frozen test**

```python
# Append to tests/test_config_frozen.py
from deerflow.config.app_config import AppConfig

def test_app_config_is_frozen():
    config = AppConfig(sandbox={"use": "test"})
    with pytest.raises(ValidationError):
        config.log_level = "debug"
```

- [ ] **Step 2: Run test — should fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_config_frozen.py::test_app_config_is_frozen -v`
Expected: FAIL

- [ ] **Step 3: Set `frozen=True` on AppConfig**

In `app_config.py`, change:
```python
model_config = ConfigDict(extra="allow", frozen=False)
```
to:
```python
model_config = ConfigDict(extra="allow", frozen=True)
```

- [ ] **Step 4: Run test — should pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_config_frozen.py::test_app_config_is_frozen -v`
Expected: PASS

- [ ] **Step 5: Run full test suite, fix failures**

Run: `cd backend && PYTHONPATH=. uv run pytest -x -v 2>&1 | head -100`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(config): make AppConfig frozen"
```

---

## Task 3: Purify `from_file()`

Remove the 8 `load_*_from_dict()` side-effect calls from `AppConfig.from_file()`. Sub-config data already flows through AppConfig fields — the globals are redundant.

**Files:**
- Modify: `deerflow/config/app_config.py`
- Test: `tests/test_from_file_pure.py`

- [ ] **Step 1: Write test that `from_file()` does not mutate sub-module globals**

```python
# tests/test_from_file_pure.py
from unittest.mock import patch
from deerflow.config.app_config import AppConfig


def test_from_file_does_not_call_load_functions(tmp_path):
    """from_file() must be pure — no side effects on sub-modules."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
config_version: 6
models: []
sandbox:
  use: "deerflow.sandbox.local:LocalSandboxProvider"
memory:
  enabled: false
title:
  enabled: false
""")

    load_fns = [
        "deerflow.config.app_config.load_title_config_from_dict",
        "deerflow.config.app_config.load_summarization_config_from_dict",
        "deerflow.config.app_config.load_memory_config_from_dict",
        "deerflow.config.app_config.load_subagents_config_from_dict",
        "deerflow.config.app_config.load_tool_search_config_from_dict",
        "deerflow.config.app_config.load_guardrails_config_from_dict",
        "deerflow.config.app_config.load_checkpointer_config_from_dict",
        "deerflow.config.app_config.load_stream_bridge_config_from_dict",
        "deerflow.config.app_config.load_acp_config_from_dict",
    ]

    patches = [patch(fn) for fn in load_fns]
    mocks = [p.start() for p in patches]

    result = AppConfig.from_file(str(config_file))

    for mock, fn_name in zip(mocks, load_fns):
        mock.assert_not_called(), f"{fn_name} should not be called by pure from_file()"

    for p in patches:
        p.stop()

    assert result.memory.enabled is False
    assert result.title.enabled is False
```

- [ ] **Step 2: Run test — should fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_from_file_pure.py -v`
Expected: FAIL — `from_file()` still calls `load_*_from_dict()`

- [ ] **Step 3: Remove all `load_*_from_dict()` calls from `from_file()`**

In `app_config.py`, delete these blocks from `from_file()`:

```python
# DELETE all of these:
if "title" in config_data:
    load_title_config_from_dict(config_data["title"])
if "summarization" in config_data:
    load_summarization_config_from_dict(config_data["summarization"])
if "memory" in config_data:
    load_memory_config_from_dict(config_data["memory"])
if "subagents" in config_data:
    load_subagents_config_from_dict(config_data["subagents"])
if "tool_search" in config_data:
    load_tool_search_config_from_dict(config_data["tool_search"])
if "guardrails" in config_data:
    load_guardrails_config_from_dict(config_data["guardrails"])
if "checkpointer" in config_data:
    load_checkpointer_config_from_dict(config_data["checkpointer"])
if "stream_bridge" in config_data:
    load_stream_bridge_config_from_dict(config_data["stream_bridge"])
load_acp_config_from_dict(config_data.get("acp_agents", {}))
```

Also remove the corresponding imports at the top of the file.

- [ ] **Step 4: Run test — should pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_from_file_pure.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite, fix failures**

Tests that relied on `from_file()` populating sub-module globals will now fail. Fix them by reading from AppConfig fields instead.

Run: `cd backend && PYTHONPATH=. uv run pytest -x -v 2>&1 | head -100`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(config): purify from_file() — remove side-effect load calls"
```

---

## Task 4: Replace app_config.py lifecycle with single ContextVar

Replace the current mtime/reload/push/pop machinery with a simple ContextVar.

**Files:**
- Create: `deerflow/config/context.py`
- Modify: `deerflow/config/app_config.py`
- Modify: `deerflow/config/__init__.py`
- Test: `tests/test_config_context.py`

- [ ] **Step 1: Write tests for new ContextVar-based lifecycle**

```python
# tests/test_config_context.py
import pytest
from deerflow.config.context import init_app_config, get_app_config, ConfigNotInitializedError
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig


def _make_config(**overrides) -> AppConfig:
    defaults = {"sandbox": SandboxConfig(use="test")}
    defaults.update(overrides)
    return AppConfig(**defaults)


def test_get_before_init_raises():
    """get_app_config() must raise if init_app_config() was not called."""
    # Note: this test must run in a fresh context — use contextvars.copy_context()
    import contextvars
    ctx = contextvars.copy_context()
    with pytest.raises(ConfigNotInitializedError):
        ctx.run(get_app_config)


def test_init_then_get():
    import contextvars
    config = _make_config()
    ctx = contextvars.copy_context()
    ctx.run(init_app_config, config)
    result = ctx.run(get_app_config)
    assert result is config


def test_init_replaces_previous():
    import contextvars
    config_a = _make_config(log_level="info")
    config_b = _make_config(log_level="debug")
    ctx = contextvars.copy_context()
    ctx.run(init_app_config, config_a)
    ctx.run(init_app_config, config_b)
    result = ctx.run(get_app_config)
    assert result.log_level == "debug"
```

- [ ] **Step 2: Run test — should fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_config_context.py -v`
Expected: FAIL — `context.py` does not exist yet

- [ ] **Step 3: Create `deerflow/config/context.py`**

```python
"""Single ContextVar for AppConfig lifecycle."""

from contextvars import ContextVar

from deerflow.config.app_config import AppConfig


class ConfigNotInitializedError(RuntimeError):
    """Raised when get_app_config() is called before init_app_config()."""

    def __init__(self):
        super().__init__(
            "AppConfig not initialized. Call init_app_config() at process startup."
        )


_app_config_var: ContextVar[AppConfig] = ContextVar("deerflow_app_config")


def init_app_config(config: AppConfig) -> None:
    """Set the AppConfig for the current context. Call once at process startup."""
    _app_config_var.set(config)


def get_app_config() -> AppConfig:
    """Get the current AppConfig. Raises ConfigNotInitializedError if not initialized."""
    try:
        return _app_config_var.get()
    except LookupError:
        raise ConfigNotInitializedError()
```

- [ ] **Step 4: Run test — should pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_config_context.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(config): add context.py with ContextVar-based lifecycle"
```

---

## Task 5: Migrate `get_app_config` imports to new context module

Replace the old `get_app_config` (from `app_config.py`) with the new one (from `context.py`) across all consumers. The old module's `get_app_config`, `reload_app_config`, `reset_app_config`, `set_app_config`, `push/pop_current_app_config` are deleted.

**Files:**
- Modify: `deerflow/config/__init__.py` — re-export `get_app_config` and `init_app_config` from `context.py`
- Modify: `deerflow/config/app_config.py` — delete `get_app_config`, `reload_app_config`, `reset_app_config`, `set_app_config`, `push/pop_current_app_config`, `_load_and_cache_app_config`, mtime globals
- Modify: `deerflow/client.py` — use `init_app_config` instead of `reload_app_config`
- Modify: `app/gateway/app.py` — call `init_app_config(AppConfig.from_file())` at startup
- Modify: All test files that import `get_app_config` from `deerflow.config.app_config` — point to new path

- [ ] **Step 1: Update `__init__.py` exports**

```python
# deerflow/config/__init__.py
from .context import get_app_config, init_app_config, ConfigNotInitializedError
from .app_config import AppConfig
from .extensions_config import ExtensionsConfig
from .memory_config import MemoryConfig
from .paths import Paths, get_paths
# ... keep type exports, remove getter function exports
```

- [ ] **Step 2: Delete lifecycle functions from `app_config.py`**

Delete everything after the `AppConfig` class definition: `_app_config`, `_app_config_path`, `_app_config_mtime`, `_app_config_is_custom`, `_current_app_config`, `_current_app_config_stack`, `_get_config_mtime`, `_load_and_cache_app_config`, `get_app_config`, `reload_app_config`, `reset_app_config`, `set_app_config`, `peek_current_app_config`, `push_current_app_config`, `pop_current_app_config`.

- [ ] **Step 3: Update `client.py`**

Replace:
```python
from deerflow.config.app_config import get_app_config, reload_app_config
```
With:
```python
from deerflow.config import get_app_config, init_app_config
from deerflow.config.app_config import AppConfig
```

In `__init__`, replace:
```python
if config_path is not None:
    reload_app_config(config_path)
self._app_config = get_app_config()
```
With:
```python
config = AppConfig.from_file(config_path)
init_app_config(config)
self._app_config = config
```

- [ ] **Step 4: Update `app/gateway/app.py`**

Add at startup:
```python
from deerflow.config import init_app_config
from deerflow.config.app_config import AppConfig

init_app_config(AppConfig.from_file())
```

- [ ] **Step 5: Run full test suite, fix import paths**

Run: `cd backend && PYTHONPATH=. uv run pytest -x -v 2>&1 | head -100`

Every test that patches `deerflow.config.app_config.get_app_config` or `deerflow.client.reload_app_config` needs updating. The new patch target is `deerflow.config.context.get_app_config` (or via `deerflow.config.get_app_config` depending on import).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(config): migrate to ContextVar-based get_app_config"
```

---

## Task 6: Delete sub-config module globals (memory, title, summarization)

Migrate the three most-used sub-config getters. Each follows the same pattern: delete the module-level global + getter/setter/loader, update consumers to use `get_app_config().xxx`.

**Files:**
- Modify: `deerflow/config/memory_config.py` — delete `_memory_config`, `get_memory_config`, `set_memory_config`, `load_memory_config_from_dict`
- Modify: `deerflow/config/title_config.py` — delete `_title_config`, `get_title_config`, `set_title_config`, `load_title_config_from_dict`
- Modify: `deerflow/config/summarization_config.py` — delete globals
- Modify: 6 production files that call `get_memory_config()`
- Modify: 1 production file that calls `get_title_config()`
- Modify: 1 production file that calls `get_summarization_config()`
- Modify: associated test files

- [ ] **Step 1: Delete globals from `memory_config.py`**

Delete lines 64-83 (everything after the class definition):
```python
# DELETE:
_memory_config: MemoryConfig = MemoryConfig()
def get_memory_config() -> MemoryConfig: ...
def set_memory_config(config: MemoryConfig) -> None: ...
def load_memory_config_from_dict(config_dict: dict) -> None: ...
```

- [ ] **Step 2: Migrate production consumers of `get_memory_config()`**

In each file, replace `get_memory_config()` with `get_app_config().memory`:

| File | Change |
|------|--------|
| `agents/middlewares/memory_middleware.py` | `from deerflow.config import get_app_config` → `get_app_config().memory` |
| `agents/memory/storage.py` | Same pattern |
| `agents/memory/updater.py` | Same pattern |
| `agents/memory/queue.py` | Same pattern |
| `agents/lead_agent/prompt.py` | Same pattern |
| `app/gateway/routers/memory.py` | Same pattern |

- [ ] **Step 3: Delete globals from `title_config.py`**

Delete lines 36-53.

- [ ] **Step 4: Migrate `get_title_config()` consumer**

`agents/middlewares/title_middleware.py` → `get_app_config().title`

- [ ] **Step 5: Delete globals from `summarization_config.py`**

- [ ] **Step 6: Migrate `get_summarization_config()` consumer**

`agents/lead_agent/agent.py` → `get_app_config().summarization`

- [ ] **Step 7: Fix tests**

Tests that patch `get_memory_config` / `get_title_config` / `get_summarization_config` must now patch `get_app_config` returning a config with the desired sub-config values.

Pattern:
```python
# Before
@patch("deerflow.agents.memory.updater.get_memory_config")
def test_something(mock_config):
    mock_config.return_value = MemoryConfig(enabled=False)

# After
@patch("deerflow.config.context.get_app_config")
def test_something(mock_config):
    mock_config.return_value = AppConfig(
        sandbox=SandboxConfig(use="test"),
        memory=MemoryConfig(enabled=False),
    )
```

- [ ] **Step 8: Run full test suite**

Run: `cd backend && PYTHONPATH=. uv run pytest -x -v`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(config): delete memory/title/summarization module globals"
```

---

## Task 7: Delete remaining sub-config module globals

Same pattern as Task 6 for the remaining 7 modules.

**Files:**
- Modify: `deerflow/config/subagents_config.py` — delete globals
- Modify: `deerflow/config/guardrails_config.py` — delete globals + `reset_guardrails_config`
- Modify: `deerflow/config/tool_search_config.py` — delete globals
- Modify: `deerflow/config/checkpointer_config.py` — delete globals
- Modify: `deerflow/config/stream_bridge_config.py` — delete globals
- Modify: `deerflow/config/acp_config.py` — delete globals
- Modify: `deerflow/config/extensions_config.py` — delete globals + `reload_extensions_config` + `reset_extensions_config` + `set_extensions_config`
- Modify: All consumers of these getters (see consumer map in exploration)

- [ ] **Step 1: Delete globals from `subagents_config.py`, migrate `subagents/registry.py`**

`get_subagents_app_config()` → `get_app_config().subagents`

- [ ] **Step 2: Delete globals from `guardrails_config.py`, migrate `tool_error_handling_middleware.py`**

`get_guardrails_config()` → `get_app_config().guardrails`

- [ ] **Step 3: Delete globals from `tool_search_config.py`**

No production consumers outside config system.

- [ ] **Step 4: Delete globals from `checkpointer_config.py`, migrate 2 consumers**

`get_checkpointer_config()` → `get_app_config().checkpointer`

- [ ] **Step 5: Delete globals from `stream_bridge_config.py`, migrate 1 consumer**

`get_stream_bridge_config()` → `get_app_config().stream_bridge`

- [ ] **Step 6: Delete globals from `acp_config.py`, migrate 2 consumers**

`get_acp_agents()` → derive from `get_app_config()`

- [ ] **Step 7: Delete globals from `extensions_config.py`, migrate 4 production consumers**

`get_extensions_config()` → `get_app_config().extensions`
`reload_extensions_config()` → `init_app_config(AppConfig.from_file())`

Consumers:
- `deerflow/sandbox/tools.py`
- `deerflow/client.py`
- `app/gateway/routers/mcp.py`
- `app/gateway/routers/skills.py`

- [ ] **Step 8: Fix tests**

- [ ] **Step 9: Run full test suite**

Run: `cd backend && PYTHONPATH=. uv run pytest -x -v`

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor(config): delete all remaining sub-config module globals"
```

---

## Task 8: Update `__init__.py` exports — final cleanup

**Files:**
- Modify: `deerflow/config/__init__.py`

- [ ] **Step 1: Update exports to final state**

```python
# deerflow/config/__init__.py
from .app_config import AppConfig
from .context import ConfigNotInitializedError, get_app_config, init_app_config
from .extensions_config import ExtensionsConfig
from .memory_config import MemoryConfig
from .paths import Paths, get_paths
from .skill_evolution_config import SkillEvolutionConfig
from .skills_config import SkillsConfig
from .tracing_config import (
    get_enabled_tracing_providers,
    get_explicitly_enabled_tracing_providers,
    get_tracing_config,
    is_tracing_enabled,
    validate_enabled_tracing_providers,
)

__all__ = [
    "AppConfig",
    "ConfigNotInitializedError",
    "ExtensionsConfig",
    "MemoryConfig",
    "Paths",
    "SkillEvolutionConfig",
    "SkillsConfig",
    "get_app_config",
    "get_enabled_tracing_providers",
    "get_explicitly_enabled_tracing_providers",
    "get_paths",
    "get_tracing_config",
    "init_app_config",
    "is_tracing_enabled",
    "validate_enabled_tracing_providers",
]
```

- [ ] **Step 2: Run full test suite**

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor(config): clean up __init__.py exports"
```

---

## Task 9: Update Gateway config update flow

Gateway API currently writes config files then calls `reload_*`. Change to: write file → construct new AppConfig → `init_app_config()` → rebuild agent.

**Files:**
- Modify: `app/gateway/routers/mcp.py`
- Modify: `app/gateway/routers/skills.py`
- Modify: `deerflow/client.py` (update_mcp_config, update_skill methods)

- [ ] **Step 1: Update `mcp.py` router**

Replace `reload_extensions_config()` call with:
```python
from deerflow.config import init_app_config
from deerflow.config.app_config import AppConfig

init_app_config(AppConfig.from_file())
```

- [ ] **Step 2: Update `skills.py` router**

Same pattern.

- [ ] **Step 3: Update `client.py` methods**

In `update_mcp_config()` and `update_skill()`, replace `reload_extensions_config()` with `init_app_config(AppConfig.from_file())`.

- [ ] **Step 4: Run full test suite**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(config): Gateway updates construct new config instead of reload"
```

---

## Task 10: Create `DeerFlowContext` and wire into agent creation ✅

Completed. `DeerFlowContext` with `app_config` field created, wired into `create_agent(context_schema=DeerFlowContext)` and `DeerFlowClient.stream(context=...)`.

---

## Task 11: Expand DeerFlowContext with `thread_id` and `agent_name`, add `resolve_context()`

Expand `DeerFlowContext` from config-only to full per-invocation context. Add `resolve_context()` helper for unified access across all entry points.

**Files:**
- Modify: `deerflow/config/deer_flow_context.py`
- Test: `tests/test_deer_flow_context.py` (extend)

- [ ] **Step 1: Write tests for expanded DeerFlowContext**

```python
# Extend tests/test_deer_flow_context.py
from unittest.mock import patch
from deerflow.config.deer_flow_context import DeerFlowContext, resolve_context

def test_deer_flow_context_fields():
    config = AppConfig(sandbox=SandboxConfig(use="test"))
    ctx = DeerFlowContext(app_config=config, thread_id="t1", agent_name="test-agent")
    assert ctx.thread_id == "t1"
    assert ctx.agent_name == "test-agent"
    assert ctx.app_config is config

def test_deer_flow_context_agent_name_default():
    config = AppConfig(sandbox=SandboxConfig(use="test"))
    ctx = DeerFlowContext(app_config=config, thread_id="t1")
    assert ctx.agent_name is None

def test_resolve_context_returns_typed_context():
    """When runtime.context is DeerFlowContext, return it directly."""
    config = AppConfig(sandbox=SandboxConfig(use="test"))
    ctx = DeerFlowContext(app_config=config, thread_id="t1")
    runtime = MagicMock()
    runtime.context = ctx
    assert resolve_context(runtime) is ctx

def test_resolve_context_fallback_from_configurable():
    """When runtime.context is None (LangGraph Server), fallback to configurable."""
    runtime = MagicMock()
    runtime.context = None
    config = AppConfig(sandbox=SandboxConfig(use="test"))
    with patch("deerflow.config.deer_flow_context.get_app_config", return_value=config), \
         patch("deerflow.config.deer_flow_context.get_config", return_value={"configurable": {"thread_id": "t2", "agent_name": "ag"}}):
        ctx = resolve_context(runtime)
        assert ctx.thread_id == "t2"
        assert ctx.agent_name == "ag"
        assert ctx.app_config is config
```

- [ ] **Step 2: Update `deer_flow_context.py`**

```python
"""Per-invocation context for DeerFlow agent execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deerflow.config.app_config import AppConfig


@dataclass(frozen=True)
class DeerFlowContext:
    """Typed, immutable, per-invocation context injected via LangGraph Runtime."""
    app_config: AppConfig
    thread_id: str
    agent_name: str | None = None


def resolve_context(runtime: Any) -> DeerFlowContext:
    """Extract or construct DeerFlowContext from runtime.

    Gateway/Client paths: runtime.context is already DeerFlowContext → return directly.
    LangGraph Server path: runtime.context is None → fallback to ContextVar + configurable.
    """
    if isinstance(runtime.context, DeerFlowContext):
        return runtime.context
    from langgraph.config import get_config
    from deerflow.config import get_app_config
    cfg = get_config().get("configurable", {})
    return DeerFlowContext(
        app_config=get_app_config(),
        thread_id=cfg.get("thread_id", ""),
        agent_name=cfg.get("agent_name"),
    )
```

- [ ] **Step 3: Run tests**

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(config): expand DeerFlowContext with thread_id, agent_name, resolve_context()"
```

---

## Task 12: Remove sandbox_id from runtime.context

Remove the mutable `sandbox_id` side channel from `runtime.context`. All sandbox_id access goes through `ThreadState.sandbox` (state channel).

**Files:**
- Modify: `deerflow/sandbox/tools.py` — delete 3× `runtime.context["sandbox_id"] = sandbox_id`
- Modify: `deerflow/sandbox/middleware.py` — delete context fallback in `after_agent`
- Test: `tests/test_sandbox_*.py` (verify existing tests still pass)

- [ ] **Step 1: Delete sandbox_id writes from `sandbox/tools.py`**

Remove lines:
- `tools.py:813`: `runtime.context["sandbox_id"] = sandbox_id`
- `tools.py:849`: `runtime.context["sandbox_id"] = sandbox_id`
- `tools.py:872`: `runtime.context["sandbox_id"] = sandbox_id`

- [ ] **Step 2: Delete context fallback from `sandbox/middleware.py:after_agent`**

Remove lines 76-80:
```python
# DELETE:
if (runtime.context or {}).get("sandbox_id") is not None:
    sandbox_id = runtime.context.get("sandbox_id")
    logger.info(f"Releasing sandbox {sandbox_id} from context")
    get_sandbox_provider().release(sandbox_id)
    return None
```

The state-based path (lines 69-74) already handles all cases.

- [ ] **Step 3: Run sandbox tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ -k sandbox -v`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): remove sandbox_id from runtime.context, use state channel only"
```

---

## Task 13: Wire DeerFlowContext into Gateway runtime and DeerFlowClient

Update the two primary entry points to construct and pass full `DeerFlowContext`.

**Files:**
- Modify: `deerflow/runtime/runs/worker.py` — replace dict context with DeerFlowContext
- Modify: `deerflow/client.py` — add thread_id to DeerFlowContext construction
- Test: existing client/runtime tests

- [ ] **Step 1: Update `worker.py`**

Replace:
```python
runtime = Runtime(context={"thread_id": thread_id}, store=store)
```
With:
```python
from deerflow.config.deer_flow_context import DeerFlowContext
from deerflow.config import get_app_config

context = DeerFlowContext(app_config=get_app_config(), thread_id=thread_id)
```
And pass `context=context` to the `agent.astream()` call instead of injecting `__pregel_runtime` manually.

Also remove the dict-style `config["context"].setdefault("thread_id", ...)` line.

- [ ] **Step 2: Update `client.py`**

Replace:
```python
context = DeerFlowContext(app_config=self._app_config)
```
With:
```python
context = DeerFlowContext(app_config=self._app_config, thread_id=thread_id)
```

Where `thread_id` comes from the `kwargs` or config.

- [ ] **Step 3: Run full test suite**

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(config): wire DeerFlowContext into Gateway runtime and DeerFlowClient"
```

---

## Task 14: Migrate middleware/tools from dict access to `resolve_context()`

Replace all `runtime.context.get("thread_id")` / `(runtime.context or {}).get(...)` patterns with `resolve_context(runtime).thread_id`.

**Files (middleware):**
- `deerflow/agents/middlewares/thread_data_middleware.py`
- `deerflow/agents/middlewares/uploads_middleware.py`
- `deerflow/agents/middlewares/memory_middleware.py`
- `deerflow/agents/middlewares/loop_detection_middleware.py`
- `deerflow/sandbox/middleware.py`

**Files (tools):**
- `deerflow/tools/builtins/present_file_tool.py`
- `deerflow/tools/builtins/setup_agent_tool.py`
- `deerflow/tools/builtins/task_tool.py`
- `deerflow/tools/skill_manage_tool.py`
- `deerflow/sandbox/tools.py`

- [ ] **Step 1: Update all middleware**

Pattern:
```python
# Before
thread_id = (runtime.context or {}).get("thread_id")
if thread_id is None:
    config = get_config()
    thread_id = config.get("configurable", {}).get("thread_id")

# After
from deerflow.config.deer_flow_context import resolve_context
ctx = resolve_context(runtime)
thread_id = ctx.thread_id
```

- [ ] **Step 2: Update all tools**

Same pattern. For tools using `ToolRuntime`, `resolve_context()` works identically.

- [ ] **Step 3: Fix tests**

Tests that mock `runtime.context` as a dict need to either:
- Pass a `DeerFlowContext` instance
- Or mock `runtime.context = None` with configurable fallback (LangGraph Server path)

- [ ] **Step 4: Run full test suite**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(config): migrate middleware/tools to resolve_context() typed access"
```

---

## Task 15: Migrate middleware to read config from Runtime

Convert middleware from global getter to reading `app_config` from `resolve_context()` at execution time.

**Files:**
- Modify: `deerflow/agents/middlewares/memory_middleware.py` — `get_app_config().memory` → `resolve_context(runtime).app_config.memory`
- Modify: `deerflow/agents/middlewares/title_middleware.py` — same pattern for `.title`
- Modify: associated tests

- [ ] **Step 1: Update MemoryMiddleware**

```python
ctx = resolve_context(runtime)
memory_config = ctx.app_config.memory
if not memory_config.enabled:
    return None
```

- [ ] **Step 2: Update TitleMiddleware**

```python
ctx = resolve_context(runtime)
title_config = ctx.app_config.title
```

- [ ] **Step 3: Fix tests**

- [ ] **Step 4: Run full test suite**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(config): middleware reads config from Runtime[DeerFlowContext]"
```

---

## Task 16: Final cleanup and verification

- [ ] **Step 1: Grep for remaining dict-style context access**

```bash
cd backend && grep -rn 'runtime\.context\.get\|runtime\.context\[' --include="*.py" packages/ | grep -v __pycache__
```

Expected: No matches in production code.

- [ ] **Step 2: Grep for remaining deleted function references**

```bash
cd backend && grep -rn "get_memory_config\|get_title_config\|get_summarization_config\|get_subagents_app_config\|get_guardrails_config\|get_tool_search_config\|get_checkpointer_config\|get_stream_bridge_config\|get_acp_agents\|reload_app_config\|reload_extensions_config\|reset_app_config\|reset_extensions_config\|reset_guardrails_config\|set_app_config\|set_extensions_config\|push_current_app_config\|pop_current_app_config\|load_memory_config_from_dict\|load_title_config_from_dict" --include="*.py" | grep -v __pycache__
```

Expected: No matches (or only in comments/docs).

- [ ] **Step 3: Run full test suite**

```bash
cd backend && PYTHONPATH=. uv run pytest -v
```

Expected: All tests pass.

- [ ] **Step 4: Run linter**

```bash
cd backend && make lint
```

- [ ] **Step 5: Commit any final fixes**

```bash
git add -A
git commit -m "refactor(config): final cleanup — remove dead references"
```

- [ ] **Step 6: Update CLAUDE.md**

Update the Configuration System section in `backend/CLAUDE.md` to reflect the new architecture:
- `get_app_config()` backed by ContextVar (no mtime/reload)
- `init_app_config()` called at process startup
- Sub-config accessed via `get_app_config().memory`, etc.
- `DeerFlowContext` with `thread_id`, `agent_name`, `app_config` for agent execution path
- `resolve_context()` for unified access across Gateway/Client/LangGraph Server paths
- `sandbox_id` flows through state channel, not context
- All config models frozen

- [ ] **Step 7: Commit docs update**

```bash
git add backend/CLAUDE.md
git commit -m "docs: update CLAUDE.md for new config architecture"
```
