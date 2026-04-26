from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, set_extensions_config
from deerflow.config.feynman_config import FeynmanConfig, load_feynman_config_from_dict
from deerflow.tools.builtins.invoke_feynman_tool import build_invoke_feynman_tool
from deerflow.tools.tools import get_available_tools


@pytest.fixture(autouse=True)
def _isolate_paths(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    paths = paths_module.Paths(base_dir=tmp_path)
    monkeypatch.setattr(paths_module, "get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.tools.delegated_runtime_support.get_paths", lambda: paths)
    return paths


def _runtime(thread_id: str = "thread-1", tool_call_id: str = "call-feynman-1"):
    return SimpleNamespace(context={"thread_id": thread_id}, config={"configurable": {"thread_id": thread_id}}, tool_call_id=tool_call_id)


@pytest.mark.anyio
async def test_invoke_feynman_runs_in_delegated_workspace_and_collects_artifacts(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    paths = paths_module.Paths(base_dir=tmp_path)
    uploads_dir = paths.sandbox_uploads_dir("thread-1")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / "brief.txt").write_text("compare sources", encoding="utf-8")

    events: list[dict] = []
    monkeypatch.setattr("deerflow.tools.delegated_runtime_support.get_stream_writer", lambda: events.append)

    class DummyProcess:
        returncode = 0

        async def communicate(self):
            return (b"feynman run complete", None)

        def terminate(self):
            pass

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*command, cwd, env, stdout, stderr):
        run_dir = paths.sandbox_work_dir("thread-1") / ".delegated" / "feynman"
        created_run_dir = next(run_dir.iterdir())
        (created_run_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (created_run_dir / "outputs" / "report.md").write_text("# Report\n", encoding="utf-8")
        (created_run_dir / "notes").mkdir(parents=True, exist_ok=True)
        (created_run_dir / "notes" / "summary.md").write_text("Grounded result", encoding="utf-8")
        return DummyProcess()

    monkeypatch.setattr("deerflow.tools.builtins.invoke_feynman_tool.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    tool = build_invoke_feynman_tool(
        FeynmanConfig(
            enabled=True,
            env={"FEYNMAN_MODEL": "gpt-test"},
        )
    )

    result = await tool.coroutine(
        description="Compare sources",
        prompt="Compare the main differences between two sources",
        workflow="compare",
        seed_paths=["/mnt/user-data/uploads/brief.txt"],
        expected_artifacts=["outputs/report.md"],
        runtime=_runtime(),
    )

    delegated_root = paths.sandbox_work_dir("thread-1") / ".delegated" / "feynman"
    run_dir = next(delegated_root.iterdir())
    result_payload = json.loads((run_dir / "deerflow-result.json").read_text(encoding="utf-8"))

    assert result.startswith("Feynman completed.")
    assert result_payload["status"] == "completed"
    assert result_payload["metadata"]["workflow"] == "compare"
    assert result_payload["metadata"]["copied_seed_paths"] == [f"{result_payload['virtual_dir']}/context/uploads/brief.txt"]
    assert any(artifact.endswith("/outputs/report.md") for artifact in result_payload["artifacts"])
    assert "- Active workflow hint: `compare`." in events[0]["prompt"]
    assert [event["type"] for event in events] == [
        "delegated_runtime_started",
        "delegated_runtime_progress",
        "delegated_runtime_progress",
        "delegated_runtime_completed",
    ]


@pytest.mark.anyio
async def test_invoke_feynman_rejects_invalid_workflow():
    tool = build_invoke_feynman_tool(FeynmanConfig(enabled=True))

    result = await tool.coroutine(
        description="Invalid workflow",
        prompt="noop",
        workflow="watch",
        runtime=_runtime(),
    )

    assert "Unsupported workflow 'watch'" in result


@pytest.mark.anyio
async def test_invoke_feynman_reports_command_not_found(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))

    async def fake_create_subprocess_exec(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr("deerflow.tools.builtins.invoke_feynman_tool.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    tool = build_invoke_feynman_tool(FeynmanConfig(enabled=True, command="missing-feynman"))

    result = await tool.coroutine(
        description="Missing command",
        prompt="noop",
        runtime=_runtime(),
    )

    assert "Command 'missing-feynman' was not found on PATH" in result


@pytest.mark.anyio
async def test_invoke_feynman_reports_timeout(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    paths = paths_module.Paths(base_dir=tmp_path)

    class PartialStdout:
        def __init__(self) -> None:
            self._sent = False
            self._closed = asyncio.Event()

        async def read(self, n: int) -> bytes:
            if not self._sent:
                self._sent = True
                return b"partial feynman output\n"
            await self._closed.wait()
            return b""

        def close(self) -> None:
            self._closed.set()

    class SlowProcess:
        returncode = 0
        stdout: PartialStdout

        def __init__(self) -> None:
            self.stdout = PartialStdout()

        def terminate(self):
            self.stdout.close()

        def kill(self):
            self.stdout.close()

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*command, cwd, env, stdout, stderr):
        return SlowProcess()

    monkeypatch.setattr("deerflow.tools.builtins.invoke_feynman_tool.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    tool = build_invoke_feynman_tool(FeynmanConfig(enabled=True, timeout_seconds=1))
    result = await tool.coroutine(
        description="Timeout test",
        prompt="noop",
        runtime=_runtime(),
    )

    delegated_root = paths.sandbox_work_dir("thread-1") / ".delegated" / "feynman"
    run_dir = next(delegated_root.iterdir())
    result_payload = json.loads((run_dir / "deerflow-result.json").read_text(encoding="utf-8"))

    assert "timed out" in result
    assert (run_dir / "run.log").read_text(encoding="utf-8") == "partial feynman output\n"
    assert "partial feynman output" in result_payload["summary"]


def test_get_available_tools_includes_invoke_feynman_when_enabled(monkeypatch):
    load_feynman_config_from_dict({"enabled": True})
    set_extensions_config(ExtensionsConfig(mcp_servers={}, skills={}))

    fake_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        feynman=FeynmanConfig(enabled=True),
        skill_evolution=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: fake_config)

    tools = get_available_tools(include_mcp=False, subagent_enabled=False)
    assert "invoke_feynman" in [tool.name for tool in tools]

    load_feynman_config_from_dict({})
