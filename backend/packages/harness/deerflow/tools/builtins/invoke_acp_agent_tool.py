"""Built-in tool for invoking external ACP-compatible agents."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from deerflow.tools.delegated_runtime_support import (
    copy_seed_paths,
    create_delegated_run,
    discover_artifacts,
    emit_runtime_event,
    write_result_file,
    write_task_brief,
)

logger = logging.getLogger(__name__)

_DEFAULT_ACP_ARTIFACT_PATTERNS = [
    "summary.md",
    "artifacts.json",
    "patch.diff",
    "screenshots/**/*",
    "**/*.md",
    "**/*.json",
    "**/*.diff",
]


class _InvokeACPAgentInput(BaseModel):
    agent: str = Field(description="Name of the ACP agent to invoke")
    prompt: str = Field(description="Task prompt to send to the ACP agent")
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


def _get_work_dir(thread_id: str | None) -> str:
    """Get the per-thread ACP workspace directory."""
    from deerflow.config.paths import get_paths

    paths = get_paths()
    if thread_id:
        try:
            work_dir = paths.acp_workspace_dir(thread_id)
        except ValueError:
            logger.warning("Invalid thread_id %r for ACP workspace, falling back to global", thread_id)
            work_dir = paths.base_dir / "acp-workspace"
    else:
        work_dir = paths.base_dir / "acp-workspace"

    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info("ACP agent work_dir: %s", work_dir)
    return str(work_dir)


def _build_mcp_servers() -> dict[str, dict[str, Any]]:
    """Build ACP ``mcpServers`` config from DeerFlow's enabled MCP servers."""
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.client import build_servers_config

    return build_servers_config(ExtensionsConfig.from_file())


def _build_acp_mcp_servers() -> list[dict[str, Any]]:
    """Build ACP ``mcpServers`` payload for ``new_session``."""
    from deerflow.config.extensions_config import ExtensionsConfig

    extensions_config = ExtensionsConfig.from_file()
    enabled_servers = extensions_config.get_enabled_mcp_servers()

    mcp_servers: list[dict[str, Any]] = []
    for name, server_config in enabled_servers.items():
        transport_type = server_config.type or "stdio"
        payload: dict[str, Any] = {"name": name, "type": transport_type}

        if transport_type == "stdio":
            if not server_config.command:
                raise ValueError(f"MCP server '{name}' with stdio transport requires 'command' field")
            payload["command"] = server_config.command
            payload["args"] = server_config.args
            payload["env"] = [{"name": key, "value": value} for key, value in server_config.env.items()]
        elif transport_type in ("http", "sse"):
            if not server_config.url:
                raise ValueError(f"MCP server '{name}' with {transport_type} transport requires 'url' field")
            payload["url"] = server_config.url
            payload["headers"] = [{"name": key, "value": value} for key, value in server_config.headers.items()]
        else:
            raise ValueError(f"MCP server '{name}' has unsupported transport type: {transport_type}")

        mcp_servers.append(payload)

    return mcp_servers


def _build_permission_response(options: list[Any], *, auto_approve: bool) -> Any:
    """Build an ACP permission response."""
    from acp import RequestPermissionResponse
    from acp.schema import AllowedOutcome, DeniedOutcome

    if auto_approve:
        for preferred_kind in ("allow_once", "allow_always"):
            for option in options:
                if getattr(option, "kind", None) != preferred_kind:
                    continue

                option_id = getattr(option, "option_id", None)
                if option_id is None:
                    option_id = getattr(option, "optionId", None)
                if option_id is None:
                    continue

                return RequestPermissionResponse(
                    outcome=AllowedOutcome(outcome="selected", optionId=option_id),
                )

    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


def _format_invocation_error(agent: str, cmd: str, exc: Exception) -> str:
    """Return a user-facing ACP invocation error with actionable remediation."""
    if not isinstance(exc, FileNotFoundError):
        return f"Error invoking ACP agent '{agent}': {exc}"

    message = f"Error invoking ACP agent '{agent}': Command '{cmd}' was not found on PATH."
    if cmd == "codex-acp" and shutil.which("codex"):
        return f"{message} The installed `codex` CLI does not speak ACP directly. Install a Codex ACP adapter (for example `npx @zed-industries/codex-acp`) or update `acp_agents.codex.command` and `args` in config.yaml."

    return f"{message} Install the agent binary or update `acp_agents.{agent}.command` in config.yaml."


def _derive_description(agent: str, description: str, prompt: str) -> str:
    if description.strip():
        return description.strip()
    normalized = " ".join(prompt.strip().split())
    if normalized:
        return normalized[:80]
    return f"ACP: {agent}"


def _resolve_runtime(runtime: ToolRuntime | None) -> tuple[str | None, str]:
    thread_id = None
    if runtime is not None:
        context = getattr(runtime, "context", None) or {}
        config = getattr(runtime, "config", None) or {}
        thread_id = context.get("thread_id") or config.get("configurable", {}).get("thread_id")
        tool_call_id = getattr(runtime, "tool_call_id", None)
        if tool_call_id:
            return thread_id, tool_call_id
    return thread_id, "invoke_acp_agent"


def _resolve_agent_env(agent_env_config: dict[str, str]) -> dict[str, str] | None:
    if not agent_env_config:
        return None
    return {k: (os.environ.get(v[1:], "") if v.startswith("$") else v) for k, v in agent_env_config.items()}


def _append_runtime_contract(
    *,
    agent: str,
    prompt: str,
    run_id: str,
    copied_seed_paths: list[str],
    expected_outputs: list[str],
) -> str:
    lines = [prompt.strip()]
    contract: list[str] = []

    inputs_dir = f"./inputs/{run_id}/"
    output_dir = f"./deerflow/{run_id}/"
    if copied_seed_paths:
        contract.append(f"- Context files have been copied into `{inputs_dir}`.")
    contract.append(f"- Write DeerFlow-facing outputs under `{output_dir}`.")
    if expected_outputs:
        contract.append("- Expected outputs:")
        contract.extend([f"  - {path}" for path in expected_outputs])

    if agent == "openhands":
        contract.extend(
            [
                f"- Required file: `{output_dir}summary.md`.",
                f"- Required file: `{output_dir}artifacts.json`.",
                f"- Optional patch file: `{output_dir}patch.diff`.",
                f"- Optional screenshots: `{output_dir}screenshots/*`.",
                f"- Do not write outside `{output_dir}` except for temporary work files.",
            ]
        )

    if contract:
        lines.extend(["", "DeerFlow runtime contract:", *contract])
    return "\n".join(lines).strip()


def _read_text_if_exists(path: Path, *, max_chars: int = 4000) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None
    return text[:max_chars]


def _result_file_virtual_path(paths) -> str:
    return f"{paths.virtual_dir.rstrip('/')}/deerflow-result.json"


def _format_artifact_lines(artifacts: list[str]) -> str:
    if not artifacts:
        return "- (none)"
    return "\n".join(f"- {artifact}" for artifact in artifacts)


def build_invoke_acp_agent_tool(agents: dict) -> BaseTool:
    """Create the ``invoke_acp_agent`` tool with a dynamic description."""
    agent_lines = "\n".join(f"- {name}: {cfg.description}" for name, cfg in agents.items())
    description = (
        "Invoke an external ACP-compatible agent and return its final response.\n\n"
        "Available agents:\n"
        f"{agent_lines}\n\n"
        "IMPORTANT: ACP agents operate in their own independent workspace. "
        "Do NOT include /mnt/user-data paths in the prompt. "
        "Use seed_paths when DeerFlow should copy /mnt/user-data files into the ACP workspace before launch. "
        "After the agent completes, its output files are accessible at /mnt/acp-workspace/."
    )

    _agents = dict(agents)

    @tool("invoke_acp_agent", args_schema=_InvokeACPAgentInput)
    async def invoke_acp_agent(
        agent: str,
        prompt: str,
        description: str = "",
        seed_paths: list[str] | None = None,
        expected_outputs: list[str] | None = None,
        runtime: ToolRuntime | None = None,
    ) -> str:
        """Invoke an external ACP-compatible agent in its own isolated workspace."""
        logger.info("Invoking ACP agent %s (prompt length: %d)", agent, len(prompt))
        logger.debug("Invoking ACP agent %s with prompt: %.200s%s", agent, prompt, "..." if len(prompt) > 200 else "")
        if agent not in _agents:
            available = ", ".join(_agents.keys())
            return f"Error: Unknown agent '{agent}'. Available: {available}"

        seed_paths = list(seed_paths or [])
        expected_outputs = list(expected_outputs or [])
        agent_config = _agents[agent]
        thread_id, tool_call_id = _resolve_runtime(runtime)
        delegated_runtime = "openhands" if agent == "openhands" else "acp"
        delegated_description = _derive_description(agent, description, prompt)
        run_paths = create_delegated_run(
            runtime=delegated_runtime,
            thread_id=thread_id,
            description=delegated_description,
            location="acp",
        )

        copied_seed_paths: list[str] = []
        try:
            copied_seed_paths = copy_seed_paths(
                thread_id=thread_id,
                seed_paths=seed_paths,
                destination_dir=run_paths.inputs_dir,
            )
        except ValueError as exc:
            error = str(exc)
            write_result_file(
                paths=run_paths,
                status="failed",
                description=delegated_description,
                summary=None,
                artifacts=[],
                extra={"agent": agent, "seed_paths": seed_paths, "expected_outputs": expected_outputs, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime=delegated_runtime,
                run_id=run_paths.run_id,
                description=delegated_description,
                phase="prepare",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return f"Error invoking ACP agent '{agent}': {error}"

        effective_prompt = _append_runtime_contract(
            agent=agent,
            prompt=prompt,
            run_id=run_paths.run_id,
            copied_seed_paths=copied_seed_paths,
            expected_outputs=expected_outputs,
        )
        metadata = {
            "agent": agent,
            "seed_paths": seed_paths,
            "copied_seed_paths": copied_seed_paths,
            "expected_outputs": expected_outputs,
        }
        write_task_brief(
            paths=run_paths,
            description=delegated_description,
            prompt=effective_prompt,
            metadata=metadata,
        )

        emit_runtime_event(
            event_type="delegated_runtime_started",
            tool_call_id=tool_call_id,
            runtime=delegated_runtime,
            run_id=run_paths.run_id,
            description=delegated_description,
            phase="prepare",
            message=f"Preparing ACP session for {agent}",
            prompt=effective_prompt,
        )
        emit_runtime_event(
            event_type="delegated_runtime_progress",
            tool_call_id=tool_call_id,
            runtime=delegated_runtime,
            run_id=run_paths.run_id,
            description=delegated_description,
            phase="invoke",
            message=f"Launching ACP agent {agent}",
            virtual_dir=run_paths.virtual_dir,
        )

        cmd = agent_config.command
        args = agent_config.args or []
        physical_cwd = _get_work_dir(thread_id)
        try:
            mcp_servers = _build_acp_mcp_servers()
        except ValueError as exc:
            logger.warning(
                "Invalid MCP server configuration for ACP agent '%s'; continuing without MCP servers: %s",
                agent,
                exc,
            )
            mcp_servers = []
        agent_env = _resolve_agent_env(agent_config.env)

        try:
            from acp import PROTOCOL_VERSION, Client, spawn_agent_process, text_block
            from acp.schema import ClientCapabilities, Implementation, TextContentBlock
        except ImportError:
            error = "agent-client-protocol package is not installed. Run `uv sync` to install project dependencies."
            run_paths.log_file.write_text(error + "\n", encoding="utf-8")
            write_result_file(
                paths=run_paths,
                status="failed",
                description=delegated_description,
                summary=None,
                artifacts=[],
                extra={**metadata, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime=delegated_runtime,
                run_id=run_paths.run_id,
                description=delegated_description,
                phase="prepare",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return f"Error: {error}"

        class _CollectingClient(Client):
            """Minimal ACP client that collects streamed text from session updates."""

            def __init__(self) -> None:
                self._chunks: list[str] = []

            @property
            def collected_text(self) -> str:
                return "".join(self._chunks)

            async def session_update(self, session_id: str, update, **kwargs) -> None:  # type: ignore[override]
                try:
                    if hasattr(update, "content") and isinstance(update.content, TextContentBlock):
                        self._chunks.append(update.content.text)
                    elif hasattr(update, "content") and hasattr(update.content, "text"):
                        self._chunks.append(update.content.text)
                except Exception:
                    logger.debug("Failed to parse ACP session update", exc_info=True)

            async def request_permission(self, options, session_id: str, tool_call, **kwargs):  # type: ignore[override]
                response = _build_permission_response(options, auto_approve=agent_config.auto_approve_permissions)
                outcome = response.outcome.outcome
                if outcome == "selected":
                    logger.info("ACP permission auto-approved for tool call %s in session %s", tool_call.tool_call_id, session_id)
                else:
                    logger.warning(
                        "ACP permission denied for tool call %s in session %s (set auto_approve_permissions: true in config.yaml to enable)",
                        tool_call.tool_call_id,
                        session_id,
                    )
                return response

        client = _CollectingClient()
        try:
            async with spawn_agent_process(client, cmd, *args, env=agent_env, cwd=physical_cwd) as (conn, proc):
                logger.info("Spawning ACP agent '%s' with command '%s' and args %s in cwd %s", agent, cmd, args, physical_cwd)
                await conn.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(name="deerflow", title="DeerFlow", version="0.1.0"),
                )
                session_kwargs: dict[str, Any] = {"cwd": physical_cwd, "mcp_servers": mcp_servers}
                if agent_config.model:
                    session_kwargs["model"] = agent_config.model
                session = await conn.new_session(**session_kwargs)
                await conn.prompt(session_id=session.session_id, prompt=[text_block(effective_prompt)])

            emit_runtime_event(
                event_type="delegated_runtime_progress",
                tool_call_id=tool_call_id,
                runtime=delegated_runtime,
                run_id=run_paths.run_id,
                description=delegated_description,
                phase="collect",
                message="ACP session completed; collecting artifacts",
                virtual_dir=run_paths.virtual_dir,
            )

            artifact_patterns = expected_outputs + _DEFAULT_ACP_ARTIFACT_PATTERNS
            artifacts = discover_artifacts(
                root_dir=run_paths.deerflow_dir,
                virtual_root=run_paths.virtual_dir,
                patterns=artifact_patterns,
                max_artifacts=50,
            )
            summary_text = _read_text_if_exists(run_paths.deerflow_dir / "summary.md") or client.collected_text.strip() or "(no response)"
            run_paths.log_file.write_text(client.collected_text or "", encoding="utf-8")
            write_result_file(
                paths=run_paths,
                status="completed",
                description=delegated_description,
                summary=summary_text,
                artifacts=artifacts,
                extra=metadata,
            )
            emit_runtime_event(
                event_type="delegated_runtime_completed",
                tool_call_id=tool_call_id,
                runtime=delegated_runtime,
                run_id=run_paths.run_id,
                description=delegated_description,
                phase="complete",
                message="ACP artifacts collected",
                virtual_dir=run_paths.virtual_dir,
                result_file=_result_file_virtual_path(run_paths),
                artifacts=artifacts,
            )
            return (
                f"{'OpenHands' if agent == 'openhands' else agent} completed.\n\n"
                f"Summary:\n{summary_text}\n\n"
                f"Artifacts:\n{_format_artifact_lines(artifacts)}"
            )
        except Exception as exc:
            error = _format_invocation_error(agent, cmd, exc)
            run_paths.log_file.write_text(f"{error}\n", encoding="utf-8")
            write_result_file(
                paths=run_paths,
                status="failed",
                description=delegated_description,
                summary=None,
                artifacts=[],
                extra={**metadata, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime=delegated_runtime,
                run_id=run_paths.run_id,
                description=delegated_description,
                phase="complete",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return (
                f"{'OpenHands' if agent == 'openhands' else agent} failed.\n\n"
                f"Reason:\n{error}\n\n"
                f"Result file:\n- {_result_file_virtual_path(run_paths)}"
            )

    invoke_acp_agent.description = description
    return invoke_acp_agent
