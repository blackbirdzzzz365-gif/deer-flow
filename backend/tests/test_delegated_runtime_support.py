from __future__ import annotations

import json

import pytest

from deerflow.tools.delegated_runtime_support import (
    copy_seed_paths,
    create_delegated_run,
    discover_artifacts,
    write_result_file,
)


@pytest.fixture(autouse=True)
def _isolate_paths(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    paths = paths_module.Paths(base_dir=tmp_path)
    monkeypatch.setattr(paths_module, "get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.tools.delegated_runtime_support.get_paths", lambda: paths)
    return paths


def test_create_delegated_run_workspace_uses_thread_workspace(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    run = create_delegated_run(
        runtime="feynman",
        thread_id="thread-1",
        description="Deep Literature Review",
        location="workspace",
    )

    assert run.run_id.startswith("feynman-")
    assert run.host_dir == tmp_path / "threads" / "thread-1" / "user-data" / "workspace" / ".delegated" / "feynman" / run.run_id
    assert run.virtual_dir == f"/mnt/user-data/workspace/.delegated/feynman/{run.run_id}"
    assert run.inputs_dir == run.host_dir / "context"
    assert run.task_file == run.host_dir / "task.md"


def test_create_delegated_run_ids_are_unique_for_same_description():
    first = create_delegated_run(
        runtime="feynman",
        thread_id="thread-1",
        description="Same Description",
        location="workspace",
    )
    second = create_delegated_run(
        runtime="feynman",
        thread_id="thread-1",
        description="Same Description",
        location="workspace",
    )

    assert first.run_id != second.run_id
    assert first.host_dir != second.host_dir


def test_create_delegated_run_acp_uses_deerflow_output_dir(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    run = create_delegated_run(
        runtime="openhands",
        thread_id="thread-1",
        description="Patch bug",
        location="acp",
    )

    assert run.host_dir == tmp_path / "threads" / "thread-1" / "acp-workspace"
    assert run.deerflow_dir == run.host_dir / "deerflow" / run.run_id
    assert run.virtual_dir == f"/mnt/acp-workspace/deerflow/{run.run_id}"
    assert run.inputs_dir == run.host_dir / "inputs" / run.run_id


def test_create_delegated_run_acp_falls_back_for_invalid_thread_id(tmp_path):
    run = create_delegated_run(
        runtime="openhands",
        thread_id="../../evil",
        description="Patch bug",
        location="acp",
    )

    assert run.thread_id is None
    assert run.host_dir == tmp_path / "acp-workspace"
    assert run.result_file == tmp_path / "acp-workspace" / "deerflow" / run.run_id / "deerflow-result.json"


def test_copy_seed_paths_copies_user_data_and_rejects_non_user_data(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    paths = paths_module.Paths(base_dir=tmp_path)
    uploads_dir = paths.sandbox_uploads_dir("thread-1")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    source_file = uploads_dir / "brief.txt"
    source_file.write_text("seed", encoding="utf-8")

    run = create_delegated_run(
        runtime="feynman",
        thread_id="thread-1",
        description="Review paper",
        location="workspace",
    )

    copied = copy_seed_paths(
        thread_id="thread-1",
        seed_paths=["/mnt/user-data/uploads/brief.txt"],
        destination_dir=run.inputs_dir,
    )

    assert copied == [f"{run.virtual_dir}/context/uploads/brief.txt"]
    assert (run.inputs_dir / "uploads" / "brief.txt").read_text(encoding="utf-8") == "seed"

    try:
        copy_seed_paths(
            thread_id="thread-1",
            seed_paths=["/mnt/acp-workspace/secret.txt"],
            destination_dir=run.inputs_dir,
        )
    except ValueError as exc:
        assert "Seed path must be under /mnt/user-data/" in str(exc)
    else:
        raise AssertionError("Expected invalid seed path to be rejected")


def test_copy_seed_paths_preserves_user_data_namespaces_for_duplicate_basenames(tmp_path):
    from deerflow.config import paths as paths_module

    paths = paths_module.Paths(base_dir=tmp_path)
    uploads_dir = paths.sandbox_uploads_dir("thread-1")
    workspace_dir = paths.sandbox_work_dir("thread-1")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / "a.md").write_text("upload", encoding="utf-8")
    (workspace_dir / "a.md").write_text("workspace", encoding="utf-8")

    run = create_delegated_run(
        runtime="feynman",
        thread_id="thread-1",
        description="Review paper",
        location="workspace",
    )

    copied = copy_seed_paths(
        thread_id="thread-1",
        seed_paths=["/mnt/user-data/uploads/a.md", "/mnt/user-data/workspace/a.md"],
        destination_dir=run.inputs_dir,
    )

    assert copied == [
        f"{run.virtual_dir}/context/uploads/a.md",
        f"{run.virtual_dir}/context/workspace/a.md",
    ]
    assert (run.inputs_dir / "uploads" / "a.md").read_text(encoding="utf-8") == "upload"
    assert (run.inputs_dir / "workspace" / "a.md").read_text(encoding="utf-8") == "workspace"


def test_discover_artifacts_filters_internal_runtime_files(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    root = tmp_path / "delegated-run"
    (root / "outputs").mkdir(parents=True)
    (root / "outputs" / "report.md").write_text("report", encoding="utf-8")
    (root / "outputs" / "task.md").write_text("user task artifact", encoding="utf-8")
    (root / "deerflow-result.json").write_text("{}", encoding="utf-8")
    (root / "task.md").write_text("task", encoding="utf-8")

    artifacts = discover_artifacts(
        root_dir=root,
        virtual_root="/mnt/user-data/workspace/.delegated/feynman/run-1",
        patterns=["outputs/**/*", "*.json", "*.md"],
        max_artifacts=10,
    )

    assert artifacts == [
        "/mnt/user-data/workspace/.delegated/feynman/run-1/outputs/report.md",
        "/mnt/user-data/workspace/.delegated/feynman/run-1/outputs/task.md",
    ]


def test_write_result_file_uses_virtual_paths(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    run = create_delegated_run(
        runtime="feynman",
        thread_id="thread-1",
        description="Compare sources",
        location="workspace",
    )

    write_result_file(
        paths=run,
        status="completed",
        description="Compare sources",
        summary="done",
        artifacts=[f"{run.virtual_dir}/outputs/report.md"],
        extra={"workflow": "compare"},
    )

    payload = json.loads(run.result_file.read_text(encoding="utf-8"))
    assert payload["runtime"] == "feynman"
    assert payload["virtual_dir"] == run.virtual_dir
    assert payload["task_file"] == f"{run.virtual_dir}/task.md"
    assert payload["result_file"] == f"{run.virtual_dir}/deerflow-result.json"
    assert payload["log_file"] == f"{run.virtual_dir}/run.log"
    assert payload["metadata"]["workflow"] == "compare"
