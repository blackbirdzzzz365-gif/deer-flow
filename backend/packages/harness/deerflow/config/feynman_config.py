"""Feynman delegated runtime configuration loaded from config.yaml."""

import logging
from collections.abc import Mapping

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FeynmanConfig(BaseModel):
    """Configuration for the Feynman delegated runtime."""

    enabled: bool = Field(default=False, description="Whether the invoke_feynman tool is enabled")
    command: str = Field(default="feynman", description="Command used to launch the Feynman CLI")
    args: list[str] = Field(default_factory=list, description="Additional arguments passed before the workflow/prompt")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables injected into the Feynman subprocess")
    timeout_seconds: int = Field(default=1800, description="Maximum execution time for a single Feynman run")
    max_artifacts: int = Field(default=50, description="Maximum number of artifacts reported back to DeerFlow")
    max_log_chars: int = Field(default=20000, description="Maximum number of log characters to include in summaries/errors")
    workflows: list[str] = Field(
        default_factory=lambda: ["research", "deepresearch", "lit", "review", "audit", "compare", "draft"],
        description="Allowed Feynman workflows for the invoke_feynman tool",
    )
    artifact_globs: list[str] = Field(
        default_factory=lambda: [
            "outputs/**/*",
            "papers/**/*",
            "notes/**/*",
            "*.md",
            "*.json",
        ],
        description="Glob patterns used to discover Feynman-generated artifacts",
    )


_feynman_config = FeynmanConfig()


def get_feynman_config() -> FeynmanConfig:
    """Get the currently configured Feynman runtime settings."""
    return _feynman_config


def load_feynman_config_from_dict(config_dict: Mapping[str, object] | None) -> None:
    """Load Feynman runtime configuration from a dictionary."""
    global _feynman_config
    if config_dict is None:
        config_dict = {}
    _feynman_config = FeynmanConfig(**config_dict)
    logger.info("Feynman config loaded (enabled=%s, command=%s)", _feynman_config.enabled, _feynman_config.command)
