from __future__ import annotations

import json
from pathlib import Path

import yaml

from deerflow.config.app_config import AppConfig


def _write_config(path: Path, *, model_name: str, supports_thinking: bool) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": model_name,
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "supports_thinking": supports_thinking,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_extensions_config(path: Path) -> None:
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")


def test_init_then_get(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="test-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))
    AppConfig.init(config)

    result = AppConfig.current()
    assert result is config
    assert result.models[0].name == "test-model"


def test_init_replaces_previous(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="model-a", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config_a = AppConfig.from_file(str(config_path))
    AppConfig.init(config_a)
    assert AppConfig.current().models[0].name == "model-a"

    _write_config(config_path, model_name="model-b", supports_thinking=True)
    config_b = AppConfig.from_file(str(config_path))
    AppConfig.init(config_b)
    assert AppConfig.current().models[0].name == "model-b"
    assert AppConfig.current() is config_b


def test_config_version_check(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)

    config_path.write_text(
        yaml.safe_dump(
            {
                "config_version": 1,
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))
    assert config is not None
