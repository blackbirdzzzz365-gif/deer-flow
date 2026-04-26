"""Built-in tool for invoking the Feynman CLI as a delegated runtime."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from deerflow.config.feynman_config import FeynmanConfig
from deerflow.tools.delegated_runtime_support import (
    copy_seed_paths,
    create_delegated_run,
    discover_artifacts,
    emit_runtime_event,
    write_result_file,
    write_task_brief,
)

logger = logging.getLogger(__name__)

_WORKFLOW_COMMANDS: dict[str, list[str]] = {
    "research": [],
    "deepresearch": ["deepresearch"],
    "lit": ["lit"],
    "review": ["review"],
    "audit": ["audit"],
    "compare": ["compare"],
    "draft": ["draft"],
}


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


def _resolve_runtime(runtime: ToolRuntime | None) -> tuple[str | None, str]:
    thread_id = None
    if runtime is not None:
        context = getattr(runtime, "context", None) or {}
        config = getattr(runtime, "config", None) or {}
        thread_id = context.get("thread_id") or config.get("configurable", {}).get("thread_id")
        tool_call_id = getattr(runtime, "tool_call_id", None)
        if tool_call_id:
            return thread_id, tool_call_id
    return thread_id, "invoke_feynman"


def _result_file_virtual_path(paths) -> str:
    return f"{paths.virtual_dir.rstrip('/')}/deerflow-result.json"


def _format_artifact_lines(artifacts: list[str]) -> str:
    if not artifacts:
        return "- (none)"
    return "\n".join(f"- {artifact}" for artifact in artifacts)


def _read_text_if_exists(path: Path, *, max_chars: int) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None
    return text[:max_chars]


def _read_log_excerpt(path: Path, *, max_chars: int) -> str | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="ignore")
    if not content:
        return None
    if len(content) <= max_chars:
        return content.strip()
    return content[-max_chars:].strip()


async def _capture_process_output(process, log_file: Path) -> None:
    """Stream process output into a log file while the process is running."""
    stdout_reader = getattr(process, "stdout", None)
    if stdout_reader is None:
        stdout, _ = await process.communicate()
        output = stdout or b""
        log_file.write_bytes(output)
        return

    with log_file.open("ab") as log:
        while True:
            chunk = await stdout_reader.read(4096)
            if not chunk:
                break
            log.write(chunk)
            log.flush()
    await process.wait()


def _resolve_summary(paths, artifacts: list[str], *, max_chars: int) -> str:
    preferred_paths = [
        paths.host_dir / "outputs" / "report.md",
        paths.host_dir / "outputs" / "summary.md",
        paths.host_dir / "notes" / "summary.md",
        paths.host_dir / "README.md",
    ]
    for preferred in preferred_paths:
        text = _read_text_if_exists(preferred, max_chars=max_chars)
        if text:
            return text

    for artifact in artifacts:
        relative = artifact.removeprefix(paths.virtual_dir.rstrip("/") + "/")
        text = _read_text_if_exists(paths.host_dir / relative, max_chars=max_chars)
        if text:
            return text

    log_excerpt = _read_log_excerpt(paths.log_file, max_chars=max_chars)
    if log_excerpt:
        return f"Feynman completed without a primary markdown summary. Recent log excerpt:\n\n{log_excerpt}"

    return "Feynman completed without a summary artifact."


def _build_effective_prompt(
    *,
    prompt: str,
    workflow: str,
    run_id: str,
    copied_seed_paths: list[str],
    expected_artifacts: list[str],
) -> str:
    notes = [
        f"DeerFlow runtime notes for run `{run_id}`:",
        "- Current working directory is the delegated run directory for this task.",
        "- Context files copied by DeerFlow are under `./context/`.",
        "- Write DeerFlow-visible outputs inside this run directory, ideally under `outputs/`, `notes/`, or `papers/`.",
        f"- Active workflow hint: `{workflow}`.",
    ]
    if copied_seed_paths:
        notes.append(f"- Copied context files: {', '.join(copied_seed_paths)}.")
    if expected_artifacts:
        notes.append("- Expected artifacts:")
        notes.extend([f"  - {path}" for path in expected_artifacts])
    return f"{prompt.strip()}\n\n" + "\n".join(notes)


def build_invoke_feynman_tool(feynman_config: FeynmanConfig) -> BaseTool:
    """Create the invoke_feynman tool for the configured Feynman runtime."""
    description = (
        "Run the Feynman CLI as a delegated research runtime. "
        "Use this for evidence-heavy research, literature reviews, audits, comparisons, and artifact-rich synthesis. "
        "The tool runs inside a dedicated workspace under /mnt/user-data/workspace/.delegated/feynman/ and returns normalized artifact paths."
    )

    @tool("invoke_feynman", args_schema=_InvokeFeynmanInput)
    async def invoke_feynman(
        description: str,
        prompt: str,
        workflow: str = "research",
        seed_paths: list[str] | None = None,
        expected_artifacts: list[str] | None = None,
        runtime: ToolRuntime | None = None,
    ) -> str:
        """Run the Feynman CLI inside a delegated DeerFlow workspace and return its artifacts."""
        thread_id, tool_call_id = _resolve_runtime(runtime)
        if not thread_id:
            return "Error invoking Feynman: thread_id is required for delegated workspace runs."

        seed_paths = list(seed_paths or [])
        expected_artifacts = list(expected_artifacts or [])
        allowed_workflows = set(feynman_config.workflows)
        if workflow not in allowed_workflows:
            return f"Error invoking Feynman: Unsupported workflow '{workflow}'. Allowed: {', '.join(sorted(allowed_workflows))}"

        run_paths = create_delegated_run(
            runtime="feynman",
            thread_id=thread_id,
            description=description,
            location="workspace",
        )
        metadata = {
            "workflow": workflow,
            "seed_paths": seed_paths,
            "expected_artifacts": expected_artifacts,
        }

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
                description=description,
                summary=None,
                artifacts=[],
                extra={**metadata, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime="feynman",
                run_id=run_paths.run_id,
                description=description,
                phase="prepare",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return f"Feynman failed.\n\nReason:\n{error}\n\nResult file:\n- {_result_file_virtual_path(run_paths)}"

        metadata["copied_seed_paths"] = copied_seed_paths
        effective_prompt = _build_effective_prompt(
            prompt=prompt,
            workflow=workflow,
            run_id=run_paths.run_id,
            copied_seed_paths=copied_seed_paths,
            expected_artifacts=expected_artifacts,
        )
        write_task_brief(
            paths=run_paths,
            description=description,
            prompt=effective_prompt,
            metadata=metadata,
        )

        emit_runtime_event(
            event_type="delegated_runtime_started",
            tool_call_id=tool_call_id,
            runtime="feynman",
            run_id=run_paths.run_id,
            description=description,
            phase="prepare",
            message="Preparing Feynman delegated runtime",
            prompt=effective_prompt,
        )
        emit_runtime_event(
            event_type="delegated_runtime_progress",
            tool_call_id=tool_call_id,
            runtime="feynman",
            run_id=run_paths.run_id,
            description=description,
            phase="invoke",
            message="Launching Feynman process",
            virtual_dir=run_paths.virtual_dir,
        )

        command = [feynman_config.command, *feynman_config.args, *_WORKFLOW_COMMANDS[workflow], effective_prompt]
        env = os.environ.copy()
        env.update(feynman_config.env)

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(run_paths.host_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            error = (
                f"Command '{feynman_config.command}' was not found on PATH. "
                "Install the Feynman CLI or update `feynman.command` in config.yaml."
            )
            write_result_file(
                paths=run_paths,
                status="failed",
                description=description,
                summary=None,
                artifacts=[],
                extra={**metadata, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime="feynman",
                run_id=run_paths.run_id,
                description=description,
                phase="invoke",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return f"Feynman failed.\n\nReason:\n{error}\n\nResult file:\n- {_result_file_virtual_path(run_paths)}"

        capture_task = asyncio.create_task(_capture_process_output(process, run_paths.log_file))
        try:
            await asyncio.wait_for(asyncio.shield(capture_task), timeout=feynman_config.timeout_seconds)
        except TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
            try:
                await asyncio.wait_for(asyncio.shield(capture_task), timeout=5)
            except TimeoutError:
                capture_task.cancel()
            except Exception:
                logger.debug("Failed to finish reading Feynman output after timeout", exc_info=True)

            error = f"Feynman timed out after {feynman_config.timeout_seconds} seconds."
            log_excerpt = _read_log_excerpt(run_paths.log_file, max_chars=feynman_config.max_log_chars)
            summary = f"{error}\n\n{log_excerpt}" if log_excerpt else None
            write_result_file(
                paths=run_paths,
                status="timed_out",
                description=description,
                summary=summary,
                artifacts=[],
                extra={**metadata, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime="feynman",
                run_id=run_paths.run_id,
                description=description,
                phase="complete",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return f"Feynman failed.\n\nReason:\n{error}\n\nResult file:\n- {_result_file_virtual_path(run_paths)}"
        except Exception as exc:
            error = f"Feynman output capture failed: {exc}"
            write_result_file(
                paths=run_paths,
                status="failed",
                description=description,
                summary=None,
                artifacts=[],
                extra={**metadata, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime="feynman",
                run_id=run_paths.run_id,
                description=description,
                phase="complete",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return f"Feynman failed.\n\nReason:\n{error}\n\nResult file:\n- {_result_file_virtual_path(run_paths)}"

        if process.returncode != 0:
            error = f"Feynman exited with code {process.returncode}."
            log_excerpt = _read_log_excerpt(run_paths.log_file, max_chars=feynman_config.max_log_chars)
            summary = f"{error}\n\n{log_excerpt}" if log_excerpt else None
            write_result_file(
                paths=run_paths,
                status="failed",
                description=description,
                summary=summary,
                artifacts=[],
                extra={**metadata, "error": error},
            )
            emit_runtime_event(
                event_type="delegated_runtime_failed",
                tool_call_id=tool_call_id,
                runtime="feynman",
                run_id=run_paths.run_id,
                description=description,
                phase="complete",
                message=error,
                result_file=_result_file_virtual_path(run_paths),
                error=error,
            )
            return f"Feynman failed.\n\nReason:\n{error}\n\nResult file:\n- {_result_file_virtual_path(run_paths)}"

        emit_runtime_event(
            event_type="delegated_runtime_progress",
            tool_call_id=tool_call_id,
            runtime="feynman",
            run_id=run_paths.run_id,
            description=description,
            phase="collect",
            message="Feynman process completed; collecting artifacts",
            virtual_dir=run_paths.virtual_dir,
        )

        artifact_patterns = expected_artifacts + feynman_config.artifact_globs
        artifacts = discover_artifacts(
            root_dir=run_paths.host_dir,
            virtual_root=run_paths.virtual_dir,
            patterns=artifact_patterns,
            max_artifacts=feynman_config.max_artifacts,
        )
        summary = _resolve_summary(run_paths, artifacts, max_chars=feynman_config.max_log_chars)
        write_result_file(
            paths=run_paths,
            status="completed",
            description=description,
            summary=summary,
            artifacts=artifacts,
            extra=metadata,
        )
        emit_runtime_event(
            event_type="delegated_runtime_completed",
            tool_call_id=tool_call_id,
            runtime="feynman",
            run_id=run_paths.run_id,
            description=description,
            phase="complete",
            message="Artifacts collected",
            virtual_dir=run_paths.virtual_dir,
            result_file=_result_file_virtual_path(run_paths),
            artifacts=artifacts,
        )
        return f"Feynman completed.\n\nSummary:\n{summary}\n\nArtifacts:\n{_format_artifact_lines(artifacts)}"

    invoke_feynman.description = description
    return invoke_feynman
