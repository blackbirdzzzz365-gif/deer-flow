"""Configuration for deferred tool loading via tool_search."""

from pydantic import BaseModel, ConfigDict, Field


class ToolSearchConfig(BaseModel):
    """Configuration for deferred tool loading via tool_search.

    When enabled, MCP tools are not loaded into the agent's context directly.
    Instead, they are listed by name in the system prompt and discoverable
    via the tool_search tool at runtime.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=False,
        description="Defer tools and enable tool_search",
    )
