from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = REPO_ROOT / "scripts" / "migrate_delegated_runtime_config.py"
PRODUCTION_TEMPLATE = REPO_ROOT / "deploy" / "production" / "config.template.yaml"


def _run_migration(config_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MIGRATION_SCRIPT), str(config_path), str(PRODUCTION_TEMPLATE)],
        check=False,
        text=True,
        capture_output=True,
    )


def test_delegated_runtime_config_migration_appends_missing_sections(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "config_version: 8",
                "models: []",
                "sandbox:",
                "  use: deerflow.sandbox.local:LocalSandboxProvider",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_migration(config_path)

    assert result.returncode == 0
    migrated = config_path.read_text(encoding="utf-8")
    assert "acp_agents:" in migrated
    assert "openhands:" in migrated
    assert 'args: ["acp", "--always-approve", "--override-with-envs"]' in migrated
    assert "feynman:" in migrated
    assert "enabled: true" in migrated


def test_delegated_runtime_config_migration_fails_on_partial_openhands(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "config_version: 8",
                "acp_agents:",
                "  openhands:",
                "    command: old-openhands",
                "feynman:",
                "  enabled: true",
                "  command: feynman",
                "  args: []",
                "  timeout_seconds: 1800",
                "  max_artifacts: 50",
                "  max_log_chars: 20000",
                '  workflows: ["research", "deepresearch", "lit", "review", "audit", "compare", "draft"]',
                "  artifact_globs:",
                "    - outputs/**/*",
                "    - papers/**/*",
                "    - notes/**/*",
                '    - "*.md"',
                '    - "*.json"',
                "  env:",
                "    FEYNMAN_MODEL: $FEYNMAN_MODEL",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_migration(config_path)

    assert result.returncode != 0
    assert "Existing acp_agents.openhands block" in result.stderr
    assert "stale or partial" in result.stderr


def test_delegated_runtime_config_migration_fails_on_disabled_feynman(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "config_version: 8",
                "acp_agents:",
                "  openhands:",
                "    command: openhands",
                '    args: ["acp", "--always-approve", "--override-with-envs"]',
                "    description: OpenHands for isolated coding, browser debugging, and patch generation",
                "    auto_approve_permissions: true",
                "    env:",
                "      RUNTIME: process",
                "      LLM_MODEL: $OPENHANDS_LLM_MODEL",
                "      LLM_API_KEY: $OPENHANDS_LLM_API_KEY",
                "      LLM_BASE_URL: $OPENHANDS_LLM_BASE_URL",
                "      LLM_CUSTOM_LLM_PROVIDER: $OPENHANDS_LLM_CUSTOM_LLM_PROVIDER",
                "feynman:",
                "  enabled: false",
                "  command: feynman",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_migration(config_path)

    assert result.returncode != 0
    assert "Existing feynman block" in result.stderr
    assert "enabled: true" in result.stderr
