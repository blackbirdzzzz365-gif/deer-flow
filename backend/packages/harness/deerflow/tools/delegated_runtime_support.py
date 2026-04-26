"""Shared helpers for delegated runtime execution."""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.config import get_stream_writer

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EXCLUDED_ARTIFACT_PATHS = {
    "deerflow-result.json",
    "run-manifest.json",
    "task.md",
    "run.log",
}


@dataclass(slots=True)
class DelegatedRunPaths:
    runtime: str
    run_id: str
    slug: str
    thread_id: str | None
    host_dir: Path
    virtual_dir: str
    inputs_dir: Path
    deerflow_dir: Path
    task_file: Path
    result_file: Path
    log_file: Path
    manifest_file: Path


def slugify(value: str | None) -> str:
    """Normalize user-facing text into a short filesystem-safe slug."""
    text = (value or "").strip().lower()
    if not text:
        return "run"
    slug = _SLUG_RE.sub("-", text).strip("-")
    if not slug:
        return "run"
    return slug[:48]


def create_run_id(runtime: str, description: str) -> tuple[str, str]:
    """Create a deterministic-enough run ID and return it with the slug."""
    slug = slugify(description)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    suffix = uuid4().hex[:8]
    return f"{runtime}-{timestamp}-{suffix}-{slug}", slug


def create_delegated_run(
    *,
    runtime: str,
    thread_id: str | None,
    description: str,
    location: str,
) -> DelegatedRunPaths:
    """Create a delegated runtime directory layout."""
    paths = get_paths()
    run_id, slug = create_run_id(runtime, description)

    if location == "workspace":
        if not thread_id:
            raise ValueError("thread_id is required for workspace delegated runs")
        host_dir = paths.sandbox_work_dir(thread_id) / ".delegated" / runtime / run_id
        virtual_dir = f"/mnt/user-data/workspace/.delegated/{runtime}/{run_id}"
        inputs_dir = host_dir / "context"
        deerflow_dir = host_dir
    elif location == "acp":
        resolved_thread_id = thread_id
        if thread_id:
            try:
                host_dir = paths.acp_workspace_dir(thread_id)
            except ValueError:
                logger.warning("Invalid thread_id %r for delegated ACP run, falling back to global workspace", thread_id)
                host_dir = paths.base_dir / "acp-workspace"
                resolved_thread_id = None
        else:
            host_dir = paths.base_dir / "acp-workspace"
        virtual_dir = f"/mnt/acp-workspace/deerflow/{run_id}"
        inputs_dir = host_dir / "inputs" / run_id
        deerflow_dir = host_dir / "deerflow" / run_id
        thread_id = resolved_thread_id
    else:
        raise ValueError(f"Unsupported delegated run location: {location}")

    deerflow_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)

    task_file = deerflow_dir / "task.md"
    result_file = deerflow_dir / "deerflow-result.json"
    log_file = deerflow_dir / "run.log"
    manifest_file = deerflow_dir / "run-manifest.json"

    return DelegatedRunPaths(
        runtime=runtime,
        run_id=run_id,
        slug=slug,
        thread_id=thread_id,
        host_dir=host_dir,
        virtual_dir=virtual_dir,
        inputs_dir=inputs_dir,
        deerflow_dir=deerflow_dir,
        task_file=task_file,
        result_file=result_file,
        log_file=log_file,
        manifest_file=manifest_file,
    )


def _to_virtual_path(thread_id: str | None, path: Path) -> str:
    """Translate a host path back into the sandbox-visible virtual path."""
    paths = get_paths()
    resolved = path.resolve()

    if thread_id:
        user_data_root = paths.sandbox_user_data_dir(thread_id).resolve()
        try:
            relative = resolved.relative_to(user_data_root)
            return f"/mnt/user-data/{relative.as_posix()}"
        except ValueError:
            pass

        acp_root = paths.acp_workspace_dir(thread_id).resolve()
        try:
            relative = resolved.relative_to(acp_root)
            return "/mnt/acp-workspace" + (f"/{relative.as_posix()}" if relative.as_posix() != "." else "")
        except ValueError:
            pass

    global_acp_root = (paths.base_dir / "acp-workspace").resolve()
    try:
        relative = resolved.relative_to(global_acp_root)
        return "/mnt/acp-workspace" + (f"/{relative.as_posix()}" if relative.as_posix() != "." else "")
    except ValueError as exc:
        raise ValueError(f"Could not map host path to a virtual path: {resolved}") from exc


def copy_seed_paths(
    *,
    thread_id: str | None,
    seed_paths: list[str],
    destination_dir: Path,
) -> list[str]:
    """Copy selected /mnt/user-data paths into a delegated runtime directory."""
    if not seed_paths:
        return []
    if not thread_id:
        raise ValueError("thread_id is required when copying seed paths")

    paths = get_paths()
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied_paths: list[str] = []
    user_data_root = paths.sandbox_user_data_dir(thread_id).resolve()
    seen_targets: set[Path] = set()

    for seed_path in seed_paths:
        if not seed_path.startswith("/mnt/user-data/"):
            raise ValueError(f"Seed path must be under /mnt/user-data/: {seed_path}")

        source = paths.resolve_virtual_path(thread_id, seed_path)
        try:
            relative_source = source.resolve().relative_to(user_data_root)
        except ValueError as exc:
            raise ValueError(f"Seed path resolved outside /mnt/user-data/: {seed_path}") from exc

        target = destination_dir / relative_source
        if target in seen_targets:
            raise ValueError(f"Duplicate seed path target: {target.relative_to(destination_dir).as_posix()}")
        seen_targets.add(target)

        if source.is_dir():
            if target.exists():
                raise ValueError(f"Seed path target already exists: {target.relative_to(destination_dir).as_posix()}")
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError(f"Seed path target already exists: {target.relative_to(destination_dir).as_posix()}")
            shutil.copy2(source, target)
        copied_paths.append(_to_virtual_path(thread_id, target))

    return copied_paths


def write_task_brief(
    *,
    paths: DelegatedRunPaths,
    description: str,
    prompt: str,
    metadata: dict[str, Any],
) -> None:
    """Persist the normalized task brief and manifest for a delegated run."""
    brief = [
        f"# {description or paths.run_id}",
        "",
        f"- Runtime: `{paths.runtime}`",
        f"- Run ID: `{paths.run_id}`",
        f"- Virtual dir: `{paths.virtual_dir}`",
        "",
        "## Prompt",
        "",
        prompt.strip(),
        "",
        "## Metadata",
        "",
        "```json",
        json.dumps(metadata, indent=2, sort_keys=True),
        "```",
        "",
    ]
    paths.task_file.write_text("\n".join(brief), encoding="utf-8")

    manifest = {
        **asdict(paths),
        "host_dir": str(paths.host_dir),
        "inputs_dir": str(paths.inputs_dir),
        "deerflow_dir": str(paths.deerflow_dir),
        "task_file": str(paths.task_file),
        "result_file": str(paths.result_file),
        "log_file": str(paths.log_file),
        "manifest_file": str(paths.manifest_file),
        "description": description,
        "prompt": prompt,
        "metadata": metadata,
    }
    paths.manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def discover_artifacts(
    *,
    root_dir: Path,
    virtual_root: str,
    patterns: list[str],
    max_artifacts: int,
) -> list[str]:
    """Discover artifact files relative to a delegated runtime root."""
    if not root_dir.exists():
        return []

    discovered: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in sorted(root_dir.glob(pattern)):
            if not match.is_file():
                continue
            relative = match.relative_to(root_dir).as_posix()
            if relative in _EXCLUDED_ARTIFACT_PATHS:
                continue
            virtual_path = virtual_root.rstrip("/") + "/" + relative
            if virtual_path in seen:
                continue
            seen.add(virtual_path)
            discovered.append(virtual_path)
            if len(discovered) >= max_artifacts:
                return discovered
    return discovered


def write_result_file(
    *,
    paths: DelegatedRunPaths,
    status: str,
    description: str,
    summary: str | None,
    artifacts: list[str],
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist the normalized delegated-runtime result payload."""
    payload = {
        "runtime": paths.runtime,
        "run_id": paths.run_id,
        "status": status,
        "description": description,
        "virtual_dir": paths.virtual_dir,
        "task_file": _to_virtual_path(paths.thread_id, paths.task_file),
        "result_file": _to_virtual_path(paths.thread_id, paths.result_file),
        "log_file": _to_virtual_path(paths.thread_id, paths.log_file),
        "summary": summary,
        "artifacts": artifacts,
        "metadata": extra or {},
        "error": (extra or {}).get("error"),
    }
    paths.result_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def emit_runtime_event(
    *,
    event_type: str,
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
) -> None:
    """Emit a delegated runtime custom event if a stream writer is active."""
    try:
        writer = get_stream_writer()
    except Exception:
        logger.debug("No stream writer available for delegated runtime event")
        return

    payload = {
        "type": event_type,
        "tool_call_id": tool_call_id,
        "run_id": run_id,
        "runtime": runtime,
        "description": description,
        "phase": phase,
        "message": message,
    }
    if prompt is not None:
        payload["prompt"] = prompt
    if virtual_dir is not None:
        payload["virtual_dir"] = virtual_dir
    if result_file is not None:
        payload["result_file"] = result_file
    if artifacts is not None:
        payload["artifacts"] = artifacts
    if error is not None:
        payload["error"] = error
    writer(payload)
