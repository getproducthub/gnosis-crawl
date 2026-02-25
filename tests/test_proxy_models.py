"""Tests for ProxyConfig model and proxy fields on CrawlOptions/GhostExtractRequest."""

import pytest
from app.models import ProxyConfig, CrawlOptions, GhostExtractRequest


class TestProxyConfig:
    def test_validates_with_just_server(self):
        config = ProxyConfig(server="http://proxy.example.com:10001")
        assert config.server == "http://proxy.example.com:10001"
        assert config.username is None
        assert config.password is None
        assert config.bypass is None

    def test_validates_with_all_fields(self):
        config = ProxyConfig(
            server="http://proxy.example.com:10001",
            username="testuser",
            password="testpass123",
            bypass="localhost,127.0.0.1",
        )
        assert config.server == "http://proxy.example.com:10001"
        assert config.username == "testuser"
        assert config.password == "testpass123"
        assert config.bypass == "localhost,127.0.0.1"


class TestCrawlOptionsProxy:
    def test_proxy_defaults_to_none(self):
        opts = CrawlOptions()
        assert opts.proxy is None

    def test_proxy_accepts_proxy_config(self):
        opts = CrawlOptions(proxy=ProxyConfig(server="http://proxy:8080"))
        assert opts.proxy is not None
        assert opts.proxy.server == "http://proxy:8080"


class TestGhostExtractRequestProxy:
    def test_proxy_defaults_to_none(self):
        req = GhostExtractRequest(url="https://example.com")
        assert req.proxy is None

    def test_proxy_accepts_proxy_config(self):
        req = GhostExtractRequest(
            url="https://example.com",
            proxy=ProxyConfig(server="http://proxy:8080"),
        )
        assert req.proxy is not None
        assert req.proxy.server == "http://proxy:8080"
