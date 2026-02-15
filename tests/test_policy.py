"""Unit tests for app.policy — domain checks, gate, and redaction."""

import pytest

from app.agent.types import RunConfig, ToolCall
from app.policy.domain import check_url_policy, is_domain_allowed
from app.policy.gate import check_tool_call, PolicyVerdict
from app.policy.redaction import redact_text, redact_dict


class TestDomainPolicy:
    """check_url_policy returns None if allowed, or a denial reason string."""

    def test_public_url_allowed_no_restrictions(self):
        result = check_url_policy("https://example.com", allowed_domains=[], block_private=False)
        assert result is None  # None = allowed

    def test_allowed_domain_passes(self):
        result = check_url_policy(
            "https://example.com/page",
            allowed_domains=["example.com"],
            block_private=False,
        )
        assert result is None

    def test_disallowed_domain_blocked(self):
        result = check_url_policy(
            "https://evil.com",
            allowed_domains=["example.com"],
            block_private=False,
        )
        assert result is not None  # non-None = denied
        assert "allowlist" in result

    def test_private_range_blocked(self):
        result = check_url_policy("http://192.168.1.1", allowed_domains=[], block_private=True)
        assert result is not None

    def test_localhost_blocked(self):
        result = check_url_policy("http://127.0.0.1", allowed_domains=[], block_private=True)
        assert result is not None

    def test_private_range_allowed_when_flag_off(self):
        result = check_url_policy("http://192.168.1.1", allowed_domains=[], block_private=False)
        assert result is None

    def test_is_domain_allowed_empty_list(self):
        assert is_domain_allowed("anything.com", []) is True

    def test_is_domain_allowed_match(self):
        # is_domain_allowed takes a URL, not a bare domain
        assert is_domain_allowed("https://example.com", ["example.com"]) is True

    def test_is_domain_allowed_no_match(self):
        assert is_domain_allowed("https://evil.com", ["example.com"]) is False


class TestPolicyGate:
    def test_allowed_tool_call(self):
        call = ToolCall(id="1", name="crawl", args={"url": "https://example.com"})
        config = RunConfig(allowed_tools=[], allowed_domains=[])
        verdict = check_tool_call(call, config)
        assert verdict.allowed is True

    def test_blocked_tool_not_in_allowlist(self):
        call = ToolCall(id="1", name="dangerous_tool", args={})
        config = RunConfig(allowed_tools=["crawl", "markdown"])
        verdict = check_tool_call(call, config)
        assert verdict.allowed is False

    def test_allowed_tool_in_allowlist(self):
        call = ToolCall(id="1", name="crawl", args={})
        config = RunConfig(allowed_tools=["crawl", "markdown"])
        verdict = check_tool_call(call, config)
        assert verdict.allowed is True

    def test_private_url_in_args_blocked(self):
        call = ToolCall(id="1", name="crawl", args={"url": "http://192.168.1.1"})
        config = RunConfig(block_private_ranges=True)
        verdict = check_tool_call(call, config)
        assert verdict.allowed is False

    def test_policy_verdict_fields(self):
        v = PolicyVerdict(allowed=True, reason=None, flags=[])
        assert v.allowed is True
        assert v.reason is None


class TestRedaction:
    def test_redact_api_key(self):
        text = "My token: sk-abc123def456ghi789jkl012mno345pqr678"
        result = redact_text(text)
        assert "sk-abc" not in result
        assert "[REDACTED" in result

    def test_redact_jwt(self):
        text = "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = redact_text(text)
        assert "eyJhbGci" not in result

    def test_redact_aws_key(self):
        text = "aws_key=AKIAIOSFODNN7EXAMPLE"
        result = redact_text(text)
        assert "AKIAIOSF" not in result

    def test_normal_text_unchanged(self):
        text = "Hello world, this is normal text with no secrets."
        result = redact_text(text)
        assert result == text

    def test_redact_dict_values(self):
        d = {"api_key": "sk-secret123456789012345678901234", "name": "test"}
        result = redact_dict(d)
        assert result["name"] == "test"
        assert "sk-secret" not in str(result.get("api_key", ""))

    def test_redact_dict_nested(self):
        d = {
            "config": {
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
            },
            "name": "test",
        }
        result = redact_dict(d)
        assert result["name"] == "test"
        assert "eyJhbGci" not in str(result)
