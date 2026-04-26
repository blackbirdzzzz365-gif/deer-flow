"""Shared OpenAI-compatible provider with loop-bound async client management.

This module wraps ``langchain_openai.ChatOpenAI`` so DeerFlow can safely use
OpenAI-compatible gateways from multiple event loops without letting the
underlying async client leak across loop boundaries.

The key guarantees are:

- async clients are created lazily per event loop and per connection config
- existing config contracts keep using ``use: langchain_openai:ChatOpenAI``
- stream-close races that happen after at least one chunk was yielded are
  treated as cleanup noise instead of fatal run failures
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import traceback
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Self
from weakref import WeakKeyDictionary

import openai
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _get_default_async_httpx_client,
    _get_default_httpx_client,
    _resolve_sync_and_async_api_keys,
    global_ssl_context,
)
from pydantic import PrivateAttr, model_validator

logger = logging.getLogger(__name__)

_LOOP_CLOSED_ERROR = "Event loop is closed"


def _freeze_for_cache(value: Any) -> Any:
    """Convert nested structures into hashable cache keys."""
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_for_cache(inner)) for key, inner in value.items()))
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze_for_cache(item) for item in value)
    if callable(value):
        return ("callable", id(value))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _cacheable_client_params(client_params: dict[str, Any], async_specific: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _freeze_for_cache(client_params),
        _freeze_for_cache(async_specific),
    )


def _is_stream_close_loop_error(exc: BaseException) -> bool:
    """Detect the narrow stream-finalization race raised by openai/httpx cleanup."""
    if not isinstance(exc, RuntimeError) or str(exc) != _LOOP_CLOSED_ERROR:
        return False

    for frame in traceback.extract_tb(exc.__traceback__):
        normalized = frame.filename.replace("\\", "/")
        if "openai/_streaming.py" in normalized and frame.name in {"__stream__", "close", "__aexit__"}:
            return True
    return False


@dataclass(slots=True)
class _AsyncClientState:
    root_async_client: Any
    async_client: Any


class _LoopBoundAsyncClientRegistry:
    """Store OpenAI async clients per event loop and connection config."""

    def __init__(self) -> None:
        self._clients: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[Any, ...], _AsyncClientState]] = WeakKeyDictionary()
        self._lock = threading.Lock()

    def get_or_create(
        self,
        loop: asyncio.AbstractEventLoop,
        key: tuple[Any, ...],
        factory: Callable[[], _AsyncClientState],
    ) -> _AsyncClientState:
        with self._lock:
            per_loop = self._clients.setdefault(loop, {})
            state = per_loop.get(key)
            if state is None:
                state = factory()
                per_loop[key] = state
            return state

    async def close_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            states = list(self._clients.pop(loop, {}).values())

        for state in states:
            try:
                close = getattr(state.root_async_client, "close", None)
                if close is not None:
                    await close()
            except RuntimeError as exc:
                if str(exc) == _LOOP_CLOSED_ERROR:
                    logger.debug("Loop-bound async OpenAI client closed after loop teardown", exc_info=True)
                else:
                    raise
            except Exception:
                logger.debug("Failed to close loop-bound async OpenAI client", exc_info=True)


_ASYNC_CLIENT_REGISTRY = _LoopBoundAsyncClientRegistry()


class LoopBoundOpenAIChatModel(ChatOpenAI):
    """ChatOpenAI variant that binds async clients to the current event loop."""

    _deerflow_async_client_params: dict[str, Any] = PrivateAttr(default_factory=dict)
    _deerflow_async_specific: dict[str, Any] = PrivateAttr(default_factory=dict)
    _deerflow_async_client_key: tuple[Any, ...] | None = PrivateAttr(default=None)
    _deerflow_loop_bound_async_clients: bool = PrivateAttr(default=False)
    _deerflow_bound_loop_id: int | None = PrivateAttr(default=None)

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @model_validator(mode="after")
    def validate_environment(self) -> Self:
        """Validate environment while deferring async client creation to call time."""
        if self.n is not None and self.n < 1:
            raise ValueError("n must be at least 1.")
        if self.n is not None and self.n > 1 and self.streaming:
            raise ValueError("n must be 1 when streaming.")

        self.openai_organization = (
            self.openai_organization
            or os.getenv("OPENAI_ORG_ID")
            or os.getenv("OPENAI_ORGANIZATION")
        )
        self.openai_api_base = self.openai_api_base or os.getenv("OPENAI_API_BASE")

        if (
            all(
                getattr(self, key, None) is None
                for key in (
                    "stream_usage",
                    "openai_proxy",
                    "openai_api_base",
                    "base_url",
                    "client",
                    "root_client",
                    "async_client",
                    "root_async_client",
                    "http_client",
                    "http_async_client",
                )
            )
            and "OPENAI_BASE_URL" not in os.environ
        ):
            self.stream_usage = True

        sync_api_key_value: str | Callable[[], str] | None = None
        async_api_key_value: str | Callable[[], Awaitable[str]] | None = None
        if self.openai_api_key is not None:
            sync_api_key_value, async_api_key_value = _resolve_sync_and_async_api_keys(
                self.openai_api_key
            )

        client_params: dict[str, Any] = {
            "organization": self.openai_organization,
            "base_url": self.openai_api_base,
            "timeout": self.request_timeout,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }
        if self.max_retries is not None:
            client_params["max_retries"] = self.max_retries

        if self.openai_proxy and (self.http_client or self.http_async_client):
            raise ValueError(
                "Cannot specify 'openai_proxy' if one of "
                "'http_client'/'http_async_client' is already specified. "
                f"Received:\n{self.openai_proxy=}\n{self.http_client=}\n{self.http_async_client=}"
            )

        if not self.client:
            if sync_api_key_value is None:
                self.client = None
                self.root_client = None
            else:
                if self.openai_proxy and not self.http_client:
                    import httpx

                    self.http_client = httpx.Client(
                        proxy=self.openai_proxy,
                        verify=global_ssl_context,
                    )
                sync_specific = {
                    "http_client": self.http_client
                    or _get_default_httpx_client(self.openai_api_base, self.request_timeout),
                    "api_key": sync_api_key_value,
                }
                self.root_client = openai.OpenAI(**client_params, **sync_specific)
                self.client = self.root_client.chat.completions

        if self.async_client is not None:
            self._deerflow_loop_bound_async_clients = False
            return self

        if self.root_async_client is not None:
            self.async_client = self.root_async_client.chat.completions
            self._deerflow_loop_bound_async_clients = False
            return self

        if self.http_async_client is not None:
            async_specific = {
                "http_client": self.http_async_client,
                "api_key": async_api_key_value,
            }
            self.root_async_client = openai.AsyncOpenAI(**client_params, **async_specific)
            self.async_client = self.root_async_client.chat.completions
            self._deerflow_loop_bound_async_clients = False
            return self

        self.async_client = None
        self.root_async_client = None
        self._deerflow_async_client_params = dict(client_params)
        if self.openai_proxy:
            def _http_client_factory():
                import httpx

                return httpx.AsyncClient(
                    proxy=self.openai_proxy,
                    verify=global_ssl_context,
                )
        else:
            def _http_client_factory():
                return _get_default_async_httpx_client(
                    self.openai_api_base,
                    self.request_timeout,
                )

        self._deerflow_async_specific = {
            "api_key": async_api_key_value,
            "http_client_factory": _http_client_factory,
        }
        self._deerflow_async_client_key = _cacheable_client_params(
            client_params,
            {
                "api_key": async_api_key_value,
                "openai_proxy": self.openai_proxy,
            },
        )
        self._deerflow_loop_bound_async_clients = True
        self._deerflow_bound_loop_id = None
        return self

    def _build_async_client_state(self) -> _AsyncClientState:
        http_client_factory = self._deerflow_async_specific["http_client_factory"]
        root_async_client = openai.AsyncOpenAI(
            **self._deerflow_async_client_params,
            http_client=http_client_factory(),
            api_key=self._deerflow_async_specific.get("api_key"),
        )
        return _AsyncClientState(
            root_async_client=root_async_client,
            async_client=root_async_client.chat.completions,
        )

    def _ensure_loop_bound_async_clients(self) -> None:
        if not self._deerflow_loop_bound_async_clients:
            return

        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        if self._deerflow_bound_loop_id == loop_id and self.async_client is not None and self.root_async_client is not None:
            return

        if self._deerflow_async_client_key is None:
            raise RuntimeError("Loop-bound OpenAI async client key was not initialised")

        state = _ASYNC_CLIENT_REGISTRY.get_or_create(
            loop,
            self._deerflow_async_client_key,
            self._build_async_client_state,
        )
        self.root_async_client = state.root_async_client
        self.async_client = state.async_client
        self._deerflow_bound_loop_id = loop_id

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._ensure_loop_bound_async_clients()
        return await super()._agenerate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self._ensure_loop_bound_async_clients()
        yielded_chunk = False
        try:
            async for chunk in super()._astream(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            ):
                yielded_chunk = True
                yield chunk
        except RuntimeError as exc:
            if yielded_chunk and _is_stream_close_loop_error(exc):
                logger.warning(
                    "Suppressed OpenAI-compatible stream cleanup race after yielding output",
                    exc_info=exc,
                )
                return
            raise


async def close_loop_bound_async_clients() -> None:
    """Close all loop-bound async clients attached to the current event loop."""
    await _ASYNC_CLIENT_REGISTRY.close_loop(asyncio.get_running_loop())
