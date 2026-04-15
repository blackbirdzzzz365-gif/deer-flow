"""Configuration for stream bridge."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StreamBridgeType = Literal["memory", "redis"]


class StreamBridgeConfig(BaseModel):
    """Configuration for the stream bridge that connects agent workers to SSE endpoints."""

    model_config = ConfigDict(frozen=True)

    type: StreamBridgeType = Field(
        default="memory",
        description="Stream bridge backend type. 'memory' uses in-process asyncio.Queue (single-process only). 'redis' uses Redis Streams (planned for Phase 2, not yet implemented).",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for the redis stream bridge type. Example: 'redis://localhost:6379/0'.",
    )
    queue_maxsize: int = Field(
        default=256,
        description="Maximum number of events buffered per run in the memory bridge.",
    )
