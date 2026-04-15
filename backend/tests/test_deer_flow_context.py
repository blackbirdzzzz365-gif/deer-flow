"""Tests for DeerFlowContext and resolve_context()."""

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.deer_flow_context import DeerFlowContext, resolve_context
from deerflow.config.sandbox_config import SandboxConfig


def _make_config(**overrides) -> AppConfig:
    defaults = {"sandbox": SandboxConfig(use="test")}
    defaults.update(overrides)
    return AppConfig(**defaults)


class TestDeerFlowContext:
    def test_frozen(self):
        ctx = DeerFlowContext(app_config=_make_config(), thread_id="t1")
        with pytest.raises(FrozenInstanceError):
            ctx.app_config = _make_config()

    def test_fields(self):
        config = _make_config()
        ctx = DeerFlowContext(app_config=config, thread_id="t1", agent_name="test-agent")
        assert ctx.thread_id == "t1"
        assert ctx.agent_name == "test-agent"
        assert ctx.app_config is config

    def test_agent_name_default(self):
        ctx = DeerFlowContext(app_config=_make_config(), thread_id="t1")
        assert ctx.agent_name is None

    def test_thread_id_required(self):
        with pytest.raises(TypeError):
            DeerFlowContext(app_config=_make_config())  # type: ignore[call-arg]


class TestResolveContext:
    def test_returns_typed_context_directly(self):
        """Gateway/Client path: runtime.context is DeerFlowContext → return as-is."""
        config = _make_config()
        ctx = DeerFlowContext(app_config=config, thread_id="t1")
        runtime = MagicMock()
        runtime.context = ctx
        assert resolve_context(runtime) is ctx

    def test_fallback_from_configurable(self):
        """LangGraph Server path: runtime.context is None → construct from ContextVar + configurable."""
        runtime = MagicMock()
        runtime.context = None
        config = _make_config()
        with (
            patch.object(AppConfig, "current", return_value=config),
            patch("langgraph.config.get_config", return_value={"configurable": {"thread_id": "t2", "agent_name": "ag"}}),
        ):
            ctx = resolve_context(runtime)
            assert ctx.thread_id == "t2"
            assert ctx.agent_name == "ag"
            assert ctx.app_config is config

    def test_fallback_empty_configurable(self):
        """LangGraph Server path with no thread_id in configurable → empty string."""
        runtime = MagicMock()
        runtime.context = None
        config = _make_config()
        with (
            patch.object(AppConfig, "current", return_value=config),
            patch("langgraph.config.get_config", return_value={"configurable": {}}),
        ):
            ctx = resolve_context(runtime)
            assert ctx.thread_id == ""
            assert ctx.agent_name is None

    def test_fallback_from_dict_context(self):
        """Legacy path: runtime.context is a dict → extract from dict directly."""
        runtime = MagicMock()
        runtime.context = {"thread_id": "old-dict", "agent_name": "from-dict"}
        config = _make_config()
        with patch.object(AppConfig, "current", return_value=config):
            ctx = resolve_context(runtime)
            assert ctx.thread_id == "old-dict"
            assert ctx.agent_name == "from-dict"
            assert ctx.app_config is config
