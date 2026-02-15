"""Unit tests for app.agent.errors — typed error hierarchy."""

import pytest

from app.agent.errors import (
    AgentError,
    ExecutionError,
    PolicyDeniedError,
    ProviderError,
    StopConditionError,
    ToolTimeoutError,
    ToolUnavailableError,
    ValidationError,
)


class TestAgentError:
    def test_base_error(self):
        err = AgentError("something broke")
        assert str(err) == "something broke"
        assert err.code == "agent_error"
        assert err.retriable is False

    def test_is_exception(self):
        with pytest.raises(AgentError):
            raise AgentError("test")


class TestValidationError:
    def test_code(self):
        err = ValidationError("bad input")
        assert err.code == "validation_error"
        assert err.retriable is False


class TestPolicyDeniedError:
    def test_code(self):
        err = PolicyDeniedError("blocked domain")
        assert err.code == "policy_denied"
        assert err.retriable is False


class TestToolTimeoutError:
    def test_code_and_retriable(self):
        err = ToolTimeoutError("tool timed out after 30s")
        assert err.code == "tool_timeout"
        assert err.retriable is True


class TestToolUnavailableError:
    def test_code(self):
        err = ToolUnavailableError("tool 'foo' not found")
        assert err.code == "tool_unavailable"
        assert err.retriable is False


class TestExecutionError:
    def test_code(self):
        err = ExecutionError("kaboom")
        assert err.code == "execution_error"
        assert err.retriable is False


class TestProviderError:
    def test_code_and_retriable(self):
        err = ProviderError("API down")
        assert err.code == "provider_error"
        assert err.retriable is True


class TestStopConditionError:
    def test_code(self):
        err = StopConditionError("max_steps reached")
        assert err.code == "stop_condition"
        assert err.retriable is False


class TestInheritance:
    def test_all_inherit_from_agent_error(self):
        for cls in [
            ValidationError,
            PolicyDeniedError,
            ToolTimeoutError,
            ToolUnavailableError,
            ExecutionError,
            ProviderError,
            StopConditionError,
        ]:
            err = cls("test")
            assert isinstance(err, AgentError)
            assert isinstance(err, Exception)
