"""Tests for the built-in ACP invocation tool."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, set_extensions_config
from deerflow.tools.builtins.invoke_acp_agent_tool import (
    _build_acp_mcp_servers,
    _build_mcp_servers,
    _build_permission_response,
    _get_work_dir,
    build_invoke_acp_agent_tool,
)
from deerflow.tools.tools import get_available_tools


@pytest.fixture(autouse=True)
def _isolate_paths(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    paths = paths_module.Paths(base_dir=tmp_path)
    monkeypatch.setattr(paths_module, "get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.tools.delegated_runtime_support.get_paths", lambda: paths)
    return paths


def _runtime(thread_id: str | None = None, tool_call_id: str = "call-acp-1"):
    context = {"thread_id": thread_id} if thread_id else {}
    config = {"configurable": {"thread_id": thread_id}} if thread_id else {"configurable": {}}
    return SimpleNamespace(context=context, config=config, tool_call_id=tool_call_id)


def test_build_mcp_servers_filters_disabled_and_maps_transports():
    set_extensions_config(ExtensionsConfig(mcp_servers={"stale": McpServerConfig(enabled=True, type="stdio", command="echo")}, skills={}))
    fresh_config = ExtensionsConfig(
        mcp_servers={
            "stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["srv"]),
            "http": McpServerConfig(enabled=True, type="http", url="https://example.com/mcp"),
            "disabled": McpServerConfig(enabled=False, type="stdio", command="echo"),
        },
        skills={},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: fresh_config),
    )

    try:
        assert _build_mcp_servers() == {
            "stdio": {"transport": "stdio", "command": "npx", "args": ["srv"]},
            "http": {"transport": "http", "url": "https://example.com/mcp"},
        }
    finally:
        monkeypatch.undo()
        set_extensions_config(ExtensionsConfig(mcp_servers={}, skills={}))


def test_build_acp_mcp_servers_formats_list_payload():
    set_extensions_config(ExtensionsConfig(mcp_servers={"stale": McpServerConfig(enabled=True, type="stdio", command="echo")}, skills={}))
    fresh_config = ExtensionsConfig(
        mcp_servers={
            "stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["srv"], env={"FOO": "bar"}),
            "http": McpServerConfig(enabled=True, type="http", url="https://example.com/mcp", headers={"Authorization": "Bearer token"}),
            "disabled": McpServerConfig(enabled=False, type="stdio", command="echo"),
        },
        skills={},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: fresh_config),
    )

    try:
        assert _build_acp_mcp_servers() == [
            {
                "name": "stdio",
                "type": "stdio",
                "command": "npx",
                "args": ["srv"],
                "env": [{"name": "FOO", "value": "bar"}],
            },
            {
                "name": "http",
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": [{"name": "Authorization", "value": "Bearer token"}],
            },
        ]
    finally:
        monkeypatch.undo()
        set_extensions_config(ExtensionsConfig(mcp_servers={}, skills={}))


def test_build_permission_response_prefers_allow_once():
    response = _build_permission_response(
        [
            SimpleNamespace(kind="reject_once", optionId="deny"),
            SimpleNamespace(kind="allow_always", optionId="always"),
            SimpleNamespace(kind="allow_once", optionId="once"),
        ],
        auto_approve=True,
    )

    assert response.outcome.outcome == "selected"
    assert response.outcome.option_id == "once"


def test_build_permission_response_denies_when_no_allow_option():
    response = _build_permission_response(
        [
            SimpleNamespace(kind="reject_once", optionId="deny"),
            SimpleNamespace(kind="reject_always", optionId="deny-forever"),
        ],
        auto_approve=True,
    )

    assert response.outcome.outcome == "cancelled"


def test_build_permission_response_denies_when_auto_approve_false():
    """P1.2: When auto_approve=False, permission is always denied regardless of options."""
    response = _build_permission_response(
        [
            SimpleNamespace(kind="allow_once", optionId="once"),
            SimpleNamespace(kind="allow_always", optionId="always"),
        ],
        auto_approve=False,
    )

    assert response.outcome.outcome == "cancelled"


@pytest.mark.anyio
async def test_build_invoke_tool_description_and_unknown_agent_error():
    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(command="codex-acp", description="Codex CLI"),
            "claude_code": ACPAgentConfig(command="claude-code-acp", description="Claude Code"),
        }
    )

    assert "Available agents:" in tool.description
    assert "- codex: Codex CLI" in tool.description
    assert "- claude_code: Claude Code" in tool.description
    assert "Do NOT include /mnt/user-data paths" in tool.description
    assert "/mnt/acp-workspace/" in tool.description

    result = await tool.coroutine(agent="missing", prompt="do work")
    assert result == "Error: Unknown agent 'missing'. Available: codex, claude_code"


def test_get_work_dir_uses_base_dir_when_no_thread_id(monkeypatch, tmp_path):
    """_get_work_dir(None) uses {base_dir}/acp-workspace/ (global fallback)."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    result = _get_work_dir(None)
    expected = tmp_path / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


def test_get_work_dir_uses_per_thread_path_when_thread_id_given(monkeypatch, tmp_path):
    """P1.1: _get_work_dir(thread_id) uses {base_dir}/threads/{thread_id}/acp-workspace/."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    result = _get_work_dir("thread-abc-123")
    expected = tmp_path / "threads" / "thread-abc-123" / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


def test_get_work_dir_falls_back_to_global_for_invalid_thread_id(monkeypatch, tmp_path):
    """P1.1: Invalid thread_id (e.g. path traversal chars) falls back to global workspace."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    result = _get_work_dir("../../evil")
    expected = tmp_path / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


@pytest.mark.anyio
async def test_invoke_acp_agent_uses_fixed_acp_workspace(monkeypatch, tmp_path):
    """ACP agent uses {base_dir}/acp-workspace/ when no thread_id is available (no config)."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))

    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(
            lambda cls: ExtensionsConfig(
                mcp_servers={"github": McpServerConfig(enabled=True, type="stdio", command="npx", args=["github-mcp"])},
                skills={},
            )
        ),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return "".join(self._chunks)

        async def session_update(self, session_id: str, update, **kwargs) -> None:
            if hasattr(update, "content") and hasattr(update.content, "text"):
                self._chunks.append(update.content.text)

        async def request_permission(self, options, session_id: str, tool_call, **kwargs):
            raise AssertionError("request_permission should not be called in this test")

    class DummyConn:
        async def initialize(self, **kwargs):
            captured["initialize"] = kwargs

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="session-1")

        async def prompt(self, **kwargs):
            captured["prompt"] = kwargs
            client = captured["client"]
            await client.session_update(
                "session-1",
                SimpleNamespace(content=text_content_block("ACP result")),
            )

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, cwd):
            captured["client"] = client
            captured["spawn"] = {"cmd": cmd, "args": list(args), "cwd": cwd}

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method: str):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {"supports": []},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type(
                "TextContentBlock",
                (),
                {"__init__": lambda self, text: setattr(self, "text", text)},
            ),
        ),
    )
    text_content_block = sys.modules["acp.schema"].TextContentBlock

    expected_cwd = str(tmp_path / "acp-workspace")

    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(
                command="codex-acp",
                args=["--json"],
                description="Codex CLI",
                model="gpt-5-codex",
            )
        }
    )

    try:
        result = await tool.coroutine(
            agent="codex",
            prompt="Implement the fix",
        )
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    deerflow_root = tmp_path / "acp-workspace" / "deerflow"
    run_dir = next(deerflow_root.iterdir())
    result_payload = json.loads((run_dir / "deerflow-result.json").read_text(encoding="utf-8"))
    prompt_text = captured["prompt"]["prompt"][0]["text"]

    assert result.startswith("codex completed.")
    assert "ACP result" in result
    assert captured["spawn"] == {"cmd": "codex-acp", "args": ["--json"], "cwd": expected_cwd}
    assert captured["new_session"] == {
        "cwd": expected_cwd,
        "mcp_servers": [
            {
                "name": "github",
                "type": "stdio",
                "command": "npx",
                "args": ["github-mcp"],
                "env": [],
            }
        ],
        "model": "gpt-5-codex",
    }
    assert captured["prompt"]["session_id"] == "session-1"
    assert prompt_text.startswith("Implement the fix")
    assert "DeerFlow runtime contract:" in prompt_text
    assert f"- Write DeerFlow-facing outputs under `./deerflow/{run_dir.name}/`." in prompt_text
    assert result_payload["status"] == "completed"
    assert result_payload["summary"] == "ACP result"
    assert result_payload["artifacts"] == []
    assert result_payload["runtime"] == "acp"


@pytest.mark.anyio
async def test_invoke_acp_agent_uses_per_thread_workspace_when_thread_id_in_runtime(monkeypatch, tmp_path):
    """P1.1: When thread_id is in the tool runtime, ACP agent uses per-thread workspace."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))

    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return "".join(self._chunks)

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, cwd):
            captured["cwd"] = cwd

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    thread_id = "thread-xyz-789"
    expected_cwd = str(tmp_path / "threads" / thread_id / "acp-workspace")

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        await tool.coroutine(
            agent="codex",
            prompt="Do something",
            runtime=_runtime(thread_id),
        )
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["cwd"] == expected_cwd


@pytest.mark.anyio
async def test_invoke_openhands_copies_seed_paths_collects_artifacts_and_emits_events(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    paths = paths_module.Paths(base_dir=tmp_path)
    uploads_dir = paths.sandbox_uploads_dir("thread-openhands")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / "brief.txt").write_text("fix the failing flow", encoding="utf-8")

    events: list[dict] = []
    monkeypatch.setattr("deerflow.tools.delegated_runtime_support.get_stream_writer", lambda: events.append)

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return "".join(self._chunks)

        async def session_update(self, session_id: str, update, **kwargs) -> None:
            if hasattr(update, "content") and hasattr(update.content, "text"):
                self._chunks.append(update.content.text)

        async def request_permission(self, options, session_id: str, tool_call, **kwargs):
            raise AssertionError("request_permission should not be called in this test")

    class DummyConn:
        async def initialize(self, **kwargs):
            captured["initialize"] = kwargs

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="session-openhands")

        async def prompt(self, **kwargs):
            captured["prompt"] = kwargs
            deerflow_root = Path(captured["new_session"]["cwd"]) / "deerflow"
            run_dir = next(deerflow_root.iterdir())
            (run_dir / "summary.md").write_text("# Summary\nFixed the issue.\n", encoding="utf-8")
            (run_dir / "artifacts.json").write_text('{"artifacts":["summary.md"]}', encoding="utf-8")
            (run_dir / "patch.diff").write_text("diff --git a/file b/file\n", encoding="utf-8")
            client = captured["client"]
            await client.session_update(
                "session-openhands",
                SimpleNamespace(content=text_content_block("OpenHands streamed summary")),
            )

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd=None):
            captured["client"] = client
            captured["spawn"] = {"cmd": cmd, "args": list(args), "env": env, "cwd": cwd}

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method: str):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(
                client, cmd, *args, env=env, cwd=cwd
            ),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type(
                "TextContentBlock",
                (),
                {"__init__": lambda self, text: setattr(self, "text", text)},
            ),
        ),
    )
    text_content_block = sys.modules["acp.schema"].TextContentBlock

    tool = build_invoke_acp_agent_tool(
        {
            "openhands": ACPAgentConfig(
                command="openhands",
                args=["acp", "--always-approve"],
                description="OpenHands ACP",
            )
        }
    )

    try:
        result = await tool.coroutine(
            agent="openhands",
            prompt="Investigate and fix the failing checkout flow",
            description="Fix checkout flow",
            seed_paths=["/mnt/user-data/uploads/brief.txt"],
            expected_outputs=["summary.md", "artifacts.json", "patch.diff"],
            runtime=_runtime("thread-openhands", "call-openhands-1"),
        )
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    deerflow_root = tmp_path / "threads" / "thread-openhands" / "acp-workspace" / "deerflow"
    run_dir = next(deerflow_root.iterdir())
    run_id = run_dir.name
    result_payload = json.loads((run_dir / "deerflow-result.json").read_text(encoding="utf-8"))
    prompt_text = captured["prompt"]["prompt"][0]["text"]
    inputs_dir = tmp_path / "threads" / "thread-openhands" / "acp-workspace" / "inputs" / run_id

    assert result.startswith("OpenHands completed.")
    assert "Fixed the issue." in result
    assert (inputs_dir / "uploads" / "brief.txt").read_text(encoding="utf-8") == "fix the failing flow"
    assert "DeerFlow runtime contract:" in prompt_text
    assert f"- Context files have been copied into `./inputs/{run_id}/`." in prompt_text
    assert f"- Required file: `./deerflow/{run_id}/summary.md`." in prompt_text
    assert f"- Required file: `./deerflow/{run_id}/artifacts.json`." in prompt_text
    assert result_payload["runtime"] == "openhands"
    assert result_payload["status"] == "completed"
    assert result_payload["summary"].startswith("# Summary")
    assert result_payload["metadata"]["expected_outputs"] == ["summary.md", "artifacts.json", "patch.diff"]
    assert result_payload["metadata"]["copied_seed_paths"] == [f"/mnt/acp-workspace/inputs/{run_id}/uploads/brief.txt"]
    assert f"/mnt/acp-workspace/deerflow/{run_id}/summary.md" in result_payload["artifacts"]
    assert f"/mnt/acp-workspace/deerflow/{run_id}/artifacts.json" in result_payload["artifacts"]
    assert f"/mnt/acp-workspace/deerflow/{run_id}/patch.diff" in result_payload["artifacts"]
    assert events[0]["prompt"] == prompt_text
    assert [event["type"] for event in events] == [
        "delegated_runtime_started",
        "delegated_runtime_progress",
        "delegated_runtime_progress",
        "delegated_runtime_completed",
    ]


@pytest.mark.anyio
async def test_invoke_acp_agent_invalid_thread_id_falls_back_and_emits_events(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    events: list[dict] = []
    monkeypatch.setattr("deerflow.tools.delegated_runtime_support.get_stream_writer", lambda: events.append)
    captured: dict[str, object] = {}

    class DummyClient:
        @property
        def collected_text(self) -> str:
            return "fallback ok"

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            captured["prompt"] = kwargs

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd=None):
            captured["cwd"] = cwd

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        result = await tool.coroutine(agent="codex", prompt="Do something", runtime=_runtime("../../evil"))
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    deerflow_root = tmp_path / "acp-workspace" / "deerflow"
    run_dir = next(deerflow_root.iterdir())
    result_payload = json.loads((run_dir / "deerflow-result.json").read_text(encoding="utf-8"))

    assert result.startswith("codex completed.")
    assert captured["cwd"] == str(tmp_path / "acp-workspace")
    assert result_payload["result_file"] == f"/mnt/acp-workspace/deerflow/{run_dir.name}/deerflow-result.json"
    assert [event["type"] for event in events] == [
        "delegated_runtime_started",
        "delegated_runtime_progress",
        "delegated_runtime_progress",
        "delegated_runtime_completed",
    ]


@pytest.mark.anyio
async def test_invoke_acp_agent_passes_env_to_spawn(monkeypatch, tmp_path):
    """env map in ACPAgentConfig is passed to spawn_agent_process; $VAR values are resolved."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-from-env")

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return ""

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["env"] = env

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(
                command="codex-acp",
                description="Codex CLI",
                env={"OPENAI_API_KEY": "$TEST_OPENAI_KEY", "FOO": "bar"},
            )
        }
    )

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["env"] == {"OPENAI_API_KEY": "sk-from-env", "FOO": "bar"}


@pytest.mark.anyio
async def test_invoke_acp_agent_skips_invalid_mcp_servers(monkeypatch, tmp_path, caplog):
    """Invalid MCP config should be logged and skipped instead of failing ACP invocation."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.tools.builtins.invoke_acp_agent_tool._build_acp_mcp_servers",
        lambda: (_ for _ in ()).throw(ValueError("missing command")),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return ""

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd=None):
            captured["spawn"] = {"cmd": cmd, "args": list(args), "env": env, "cwd": cwd}

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})
    caplog.set_level("WARNING")

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["new_session"]["mcp_servers"] == []
    assert "continuing without MCP servers" in caplog.text
    assert "missing command" in caplog.text


@pytest.mark.anyio
async def test_invoke_acp_agent_passes_none_env_when_not_configured(monkeypatch, tmp_path):
    """When env is empty, None is passed to spawn_agent_process (subprocess inherits parent env)."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return ""

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["env"] = env

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["env"] is None


def test_get_available_tools_includes_invoke_acp_agent_when_agents_configured(monkeypatch):
    from deerflow.config.acp_config import load_acp_config_from_dict

    load_acp_config_from_dict(
        {
            "codex": {
                "command": "codex-acp",
                "args": [],
                "description": "Codex CLI",
            }
        }
    )

    fake_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: fake_config)
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    tools = get_available_tools(include_mcp=True, subagent_enabled=False)
    assert "invoke_acp_agent" in [tool.name for tool in tools]

    load_acp_config_from_dict({})
