from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_openai import ChatOpenAI

from deerflow.models.openai_compat_provider import (
    LoopBoundOpenAIChatModel,
    close_loop_bound_async_clients,
)


class _FakeSyncOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=SimpleNamespace(kind="sync-completions"))


class _FakeAsyncOpenAI:
    instances: list[_FakeAsyncOpenAI] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=SimpleNamespace(kind=f"async-completions-{len(self.instances) + 1}"))
        self.close_calls = 0
        self.__class__.instances.append(self)

    async def close(self):
        self.close_calls += 1


def _make_model(monkeypatch) -> LoopBoundOpenAIChatModel:
    monkeypatch.setattr(
        "deerflow.models.openai_compat_provider.openai.OpenAI",
        _FakeSyncOpenAI,
    )
    monkeypatch.setattr(
        "deerflow.models.openai_compat_provider.openai.AsyncOpenAI",
        _FakeAsyncOpenAI,
    )
    monkeypatch.setattr(
        "deerflow.models.openai_compat_provider._get_default_httpx_client",
        lambda *args, **kwargs: SimpleNamespace(kind="sync-http-client"),
    )
    monkeypatch.setattr(
        "deerflow.models.openai_compat_provider._get_default_async_httpx_client",
        lambda *args, **kwargs: SimpleNamespace(kind="async-http-client"),
    )
    return LoopBoundOpenAIChatModel(
        model="gateway-model",
        api_key="test-key",
        base_url="https://gateway.example/v1",
    )


async def _raise_stream_close_error() -> None:
    namespace: dict[str, object] = {}
    exec(
        compile(
            "async def __stream__():\n    raise RuntimeError('Event loop is closed')\n",
            "/virtualenv/site-packages/openai/_streaming.py",
            "exec",
        ),
        namespace,
    )
    await namespace["__stream__"]()  # type: ignore[index]


async def _raise_non_stream_close_error() -> None:
    namespace: dict[str, object] = {}
    exec(
        compile(
            "async def elsewhere():\n    raise RuntimeError('Event loop is closed')\n",
            "/tmp/not_stream_cleanup.py",
            "exec",
        ),
        namespace,
    )
    await namespace["elsewhere"]()  # type: ignore[index]


def test_loop_bound_provider_defers_async_client_creation(monkeypatch):
    model = _make_model(monkeypatch)

    assert model.root_client is not None
    assert model.client is not None
    assert model.root_async_client is None
    assert model.async_client is None
    assert model._deerflow_loop_bound_async_clients is True


@pytest.mark.anyio
async def test_loop_bound_provider_reuses_async_client_per_loop_and_config(monkeypatch):
    _FakeAsyncOpenAI.instances = []
    model_a = _make_model(monkeypatch)
    model_b = _make_model(monkeypatch)

    model_a._ensure_loop_bound_async_clients()
    first_async_client = model_a.async_client
    model_b._ensure_loop_bound_async_clients()

    assert first_async_client is not None
    assert model_b.async_client is first_async_client
    assert len(_FakeAsyncOpenAI.instances) == 1

    await close_loop_bound_async_clients()

    assert _FakeAsyncOpenAI.instances[0].close_calls == 1


@pytest.mark.anyio
async def test_loop_bound_provider_suppresses_stream_close_race_after_first_chunk(monkeypatch):
    _FakeAsyncOpenAI.instances = []
    model = _make_model(monkeypatch)

    async def _fake_parent_astream(self, *args, **kwargs):
        yield "chunk-1"
        await _raise_stream_close_error()

    monkeypatch.setattr(ChatOpenAI, "_astream", _fake_parent_astream)

    chunks: list[object] = []
    async for chunk in model._astream([]):
        chunks.append(chunk)

    await close_loop_bound_async_clients()

    assert chunks == ["chunk-1"]


@pytest.mark.anyio
async def test_loop_bound_provider_does_not_swallow_non_stream_runtime_error(monkeypatch):
    _FakeAsyncOpenAI.instances = []
    model = _make_model(monkeypatch)

    async def _fake_parent_astream(self, *args, **kwargs):
        yield "chunk-1"
        await _raise_non_stream_close_error()

    monkeypatch.setattr(ChatOpenAI, "_astream", _fake_parent_astream)

    with pytest.raises(RuntimeError, match="Event loop is closed"):
        async for _chunk in model._astream([]):
            pass

    await close_loop_bound_async_clients()
