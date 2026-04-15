from pydantic import BaseModel, ConfigDict, Field


class TokenUsageConfig(BaseModel):
    """Configuration for token usage tracking."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(default=False, description="Enable token usage tracking middleware")
