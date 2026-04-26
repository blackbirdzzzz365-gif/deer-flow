from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_TEMPLATE_DIRS = [
    REPO_ROOT / "deploy" / "production" / "agents",
    REPO_ROOT / "deploy" / "backup-blackbird" / "agents",
]


def test_deploy_agent_templates_have_config_and_soul():
    for agents_dir in AGENT_TEMPLATE_DIRS:
        assert agents_dir.exists(), f"Missing agents template directory: {agents_dir}"

        for agent_dir in sorted(path for path in agents_dir.iterdir() if path.is_dir()):
            config_path = agent_dir / "config.yaml"
            soul_path = agent_dir / "SOUL.md"

            assert config_path.exists(), f"Missing config.yaml for deploy agent template: {agent_dir}"
            assert soul_path.exists(), f"Missing SOUL.md for deploy agent template: {agent_dir}"

            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            assert config.get("name") == agent_dir.name
