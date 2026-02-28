"""Tests for app.proxy_pool — rotating proxy pool with sticky sessions and health tracking."""

import time

import pytest

from app.proxy_pool import ProxyEntry, ProxyPool, get_proxy_pool


class TestProxyEntry:
    """Test the ProxyEntry dataclass."""

    def test_defaults(self):
        entry = ProxyEntry(server="http://proxy:8080")
        assert entry.server == "http://proxy:8080"
        assert entry.username is None
        assert entry.password is None
        assert entry.region is None
        assert entry.provider == "direct"
        assert entry.fail_count == 0
        assert entry.is_healthy is True

    def test_to_playwright_config_server_only(self):
        entry = ProxyEntry(server="http://proxy:8080")
        config = entry.to_playwright_config()
        assert config == {"server": "http://proxy:8080"}
        assert "username" not in config
        assert "password" not in config

    def test_to_playwright_config_full(self):
        entry = ProxyEntry(
            server="http://proxy:8080",
            username="user1",
            password="pass1",
        )
        config = entry.to_playwright_config()
        assert config["server"] == "http://proxy:8080"
        assert config["username"] == "user1"
        assert config["password"] == "pass1"

    def test_is_healthy_after_failure(self):
        entry = ProxyEntry(server="http://proxy:8080", cooldown_seconds=1.0)
        entry.fail_count = 1
        entry.last_fail_ts = time.time()
        assert entry.is_healthy is False

    def test_is_healthy_after_cooldown_expires(self):
        entry = ProxyEntry(server="http://proxy:8080", cooldown_seconds=0.1)
        entry.fail_count = 1
        entry.last_fail_ts = time.time() - 0.2  # cooldown already elapsed
        assert entry.is_healthy is True


class TestProxyPoolGetProxy:
    """Test ProxyPool.get_proxy returns correct proxy dicts."""

    def test_returns_proxy_dict(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080", username="u1", password="p1"),
        ])
        result = pool.get_proxy("example.com")
        assert result is not None
        assert result["server"] == "http://proxy1:8080"
        assert result["username"] == "u1"
        assert result["password"] == "p1"

    def test_returns_none_when_pool_empty(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_PROXY_URL", raising=False)
        monkeypatch.delenv("PROXY_SERVER", raising=False)
        pool = ProxyPool(proxies=[])
        result = pool.get_proxy("example.com")
        assert result is None

    def test_returns_none_when_all_unhealthy(self):
        entry = ProxyEntry(server="http://proxy1:8080", cooldown_seconds=300.0)
        entry.fail_count = 1
        entry.last_fail_ts = time.time()
        pool = ProxyPool(proxies=[entry])
        result = pool.get_proxy("example.com")
        assert result is None


class TestStickySessions:
    """Test per-domain sticky session behavior."""

    def test_same_domain_returns_same_proxy(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080"),
            ProxyEntry(server="http://proxy2:8080"),
            ProxyEntry(server="http://proxy3:8080"),
        ])
        first = pool.get_proxy("g2.com")
        for _ in range(10):
            result = pool.get_proxy("g2.com")
            assert result == first

    def test_different_domains_can_get_different_proxies(self):
        proxies = [ProxyEntry(server=f"http://proxy{i}:8080") for i in range(20)]
        pool = ProxyPool(proxies=proxies)

        assigned_servers = set()
        for i in range(20):
            result = pool.get_proxy(f"domain{i}.com")
            assert result is not None
            assigned_servers.add(result["server"])

        assert len(assigned_servers) > 1

    def test_sticky_false_does_not_remember(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080"),
            ProxyEntry(server="http://proxy2:8080"),
        ])
        pool.get_proxy("example.com", sticky=False)
        assert "example.com" not in pool._domain_sessions


class TestHealthTracking:
    """Test mark_failed and mark_success behavior."""

    def test_mark_failed_disables_proxy_temporarily(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080", cooldown_seconds=300.0),
        ])
        result = pool.get_proxy("example.com")
        assert result is not None

        pool.mark_failed("example.com")

        result = pool.get_proxy("example.com")
        assert result is None

    def test_mark_failed_clears_sticky_session(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080", cooldown_seconds=300.0),
            ProxyEntry(server="http://proxy2:8080"),
        ])
        pool.get_proxy("example.com")
        pool.mark_failed("example.com")

        assert "example.com" not in pool._domain_sessions

    def test_mark_success_resets_fail_count(self):
        entry = ProxyEntry(server="http://proxy1:8080", cooldown_seconds=0.01)
        entry.fail_count = 3
        entry.last_fail_ts = time.time() - 1.0
        pool = ProxyPool(proxies=[entry])

        pool.get_proxy("example.com")
        pool.mark_success("example.com")

        assert entry.fail_count == 0

    def test_mark_failed_unknown_domain_is_noop(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080"),
        ])
        pool.mark_failed("unknown.com")

    def test_mark_success_unknown_domain_is_noop(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080"),
        ])
        pool.mark_success("unknown.com")


class TestSessionRotation:
    """After mark_failed, the next call for that domain gets a different proxy."""

    def test_rotates_to_different_proxy_after_failure(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080", cooldown_seconds=300.0),
            ProxyEntry(server="http://proxy2:8080", cooldown_seconds=300.0),
        ])
        first = pool.get_proxy("g2.com")
        assert first is not None
        first_server = first["server"]

        pool.mark_failed("g2.com")

        second = pool.get_proxy("g2.com")
        assert second is not None
        assert second["server"] != first_server


class TestBrightDataProxy:
    """Test Bright Data residential proxy URL parsing from env vars."""

    def test_loads_brightdata_from_env(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_PROXY_URL", "http://brd.superproxy.io:22225")
        monkeypatch.setenv("BRIGHTDATA_PROXY_USERNAME", "brd-customer-123")
        monkeypatch.setenv("BRIGHTDATA_PROXY_PASSWORD", "brightpass")
        monkeypatch.delenv("PROXY_SERVER", raising=False)

        pool = ProxyPool()
        assert pool.pool_size == 1
        proxy = pool.get_proxy("example.com")
        assert proxy is not None
        assert proxy["server"] == "http://brd.superproxy.io:22225"
        assert proxy["username"] == "brd-customer-123"
        assert proxy["password"] == "brightpass"

    def test_brightdata_entry_has_correct_provider(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_PROXY_URL", "http://brd.superproxy.io:22225")
        monkeypatch.setenv("BRIGHTDATA_PROXY_USERNAME", "brd-customer-123")
        monkeypatch.setenv("BRIGHTDATA_PROXY_PASSWORD", "brightpass")
        monkeypatch.delenv("PROXY_SERVER", raising=False)

        pool = ProxyPool()
        assert pool._proxies[0].provider == "brightdata"


class TestDirectProxyFallback:
    """Test PROXY_SERVER env var as direct proxy fallback."""

    def test_loads_direct_proxy_from_env(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_PROXY_URL", raising=False)
        monkeypatch.setenv("PROXY_SERVER", "http://gate.decodo.com:10001")
        monkeypatch.setenv("PROXY_USERNAME", "directuser")
        monkeypatch.setenv("PROXY_PASSWORD", "directpass")

        pool = ProxyPool()
        assert pool.pool_size == 1
        proxy = pool.get_proxy("example.com")
        assert proxy is not None
        assert proxy["server"] == "http://gate.decodo.com:10001"
        assert proxy["username"] == "directuser"
        assert proxy["password"] == "directpass"

    def test_direct_entry_has_correct_provider(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_PROXY_URL", raising=False)
        monkeypatch.setenv("PROXY_SERVER", "http://gate.decodo.com:10001")
        monkeypatch.delenv("PROXY_USERNAME", raising=False)
        monkeypatch.delenv("PROXY_PASSWORD", raising=False)

        pool = ProxyPool()
        assert pool._proxies[0].provider == "direct"

    def test_loads_both_brightdata_and_direct(self, monkeypatch):
        monkeypatch.setenv("BRIGHTDATA_PROXY_URL", "http://brd.superproxy.io:22225")
        monkeypatch.setenv("BRIGHTDATA_PROXY_USERNAME", "brd-user")
        monkeypatch.setenv("BRIGHTDATA_PROXY_PASSWORD", "brd-pass")
        monkeypatch.setenv("PROXY_SERVER", "http://gate.decodo.com:10001")
        monkeypatch.setenv("PROXY_USERNAME", "direct-user")
        monkeypatch.setenv("PROXY_PASSWORD", "direct-pass")

        pool = ProxyPool()
        assert pool.pool_size == 2
        providers = {p.provider for p in pool._proxies}
        assert providers == {"brightdata", "direct"}

    def test_empty_env_yields_empty_pool(self, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_PROXY_URL", raising=False)
        monkeypatch.delenv("PROXY_SERVER", raising=False)

        pool = ProxyPool()
        assert pool.pool_size == 0
        assert pool.get_proxy("example.com") is None


class TestPoolProperties:
    """Test pool_size and healthy_count properties."""

    def test_pool_size(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080"),
            ProxyEntry(server="http://proxy2:8080"),
        ])
        assert pool.pool_size == 2

    def test_healthy_count_all_healthy(self):
        pool = ProxyPool(proxies=[
            ProxyEntry(server="http://proxy1:8080"),
            ProxyEntry(server="http://proxy2:8080"),
        ])
        assert pool.healthy_count == 2

    def test_healthy_count_with_failures(self):
        healthy_entry = ProxyEntry(server="http://proxy1:8080")
        failed_entry = ProxyEntry(server="http://proxy2:8080", cooldown_seconds=300.0)
        failed_entry.fail_count = 1
        failed_entry.last_fail_ts = time.time()

        pool = ProxyPool(proxies=[healthy_entry, failed_entry])
        assert pool.healthy_count == 1


class TestGetProxyPool:
    """Test the global proxy pool factory function."""

    def test_returns_proxy_pool_instance(self, monkeypatch):
        import app.proxy_pool as mod
        monkeypatch.setattr(mod, "_global_pool", None)
        monkeypatch.delenv("BRIGHTDATA_PROXY_URL", raising=False)
        monkeypatch.delenv("PROXY_SERVER", raising=False)

        pool = get_proxy_pool()
        assert isinstance(pool, ProxyPool)

    def test_returns_same_instance_on_repeated_calls(self, monkeypatch):
        import app.proxy_pool as mod
        monkeypatch.setattr(mod, "_global_pool", None)
        monkeypatch.delenv("BRIGHTDATA_PROXY_URL", raising=False)
        monkeypatch.delenv("PROXY_SERVER", raising=False)

        pool1 = get_proxy_pool()
        pool2 = get_proxy_pool()
        assert pool1 is pool2
