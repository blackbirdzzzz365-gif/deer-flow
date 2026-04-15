"""Configuration for pre-tool-call authorization."""

from pydantic import BaseModel, ConfigDict, Field


class GuardrailProviderConfig(BaseModel):
    """Configuration for a guardrail provider."""

    model_config = ConfigDict(frozen=True)

    use: str = Field(description="Class path (e.g. 'deerflow.guardrails.builtin:AllowlistProvider')")
    config: dict = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class GuardrailsConfig(BaseModel):
    """Configuration for pre-tool-call authorization.

    When enabled, every tool call passes through the configured provider
    before execution. The provider receives tool name, arguments, and the
    agent's passport reference, and returns an allow/deny decision.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(default=False, description="Enable guardrail middleware")
    fail_closed: bool = Field(default=True, description="Block tool calls if provider errors")
    passport: str | None = Field(default=None, description="OAP passport path or hosted agent ID")
    provider: GuardrailProviderConfig | None = Field(default=None, description="Guardrail provider configuration")
