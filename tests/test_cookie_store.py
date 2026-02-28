"""Tests for app.cookie_store — per-domain cookie persistence for Cloudflare clearance reuse."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cookie_store import CookieStore, StoredCookie, get_cookie_store


# --- StoredCookie ---


class TestStoredCookie:
    def test_not_expired_when_fresh(self):
        cookie = StoredCookie(name="cf_clearance", value="abc", domain="g2.com")
        assert cookie.is_expired is False

    def test_expired_after_ttl(self):
        cookie = StoredCookie(
            name="cf_clearance",
            value="abc",
            domain="g2.com",
            stored_at=time.time() - 2000,
            ttl_seconds=1500,
        )
        assert cookie.is_expired is True

    def test_default_ttl_is_25_minutes(self):
        cookie = StoredCookie(name="cf_clearance", value="abc", domain="g2.com")
        assert cookie.ttl_seconds == 1500

    def test_custom_ttl(self):
        cookie = StoredCookie(
            name="cf_clearance", value="abc", domain="g2.com", ttl_seconds=600
        )
        assert cookie.ttl_seconds == 600

    def test_default_path(self):
        cookie = StoredCookie(name="cf_clearance", value="abc", domain="g2.com")
        assert cookie.path == "/"


# --- CookieStore._key ---


class TestCookieStoreKey:
    def test_key_with_domain_only(self):
        store = CookieStore()
        assert store._key("g2.com") == "g2.com|direct"

    def test_key_with_proxy(self):
        store = CookieStore()
        assert store._key("g2.com", "http://proxy:8080") == "g2.com|http://proxy:8080"

    def test_key_none_proxy_is_direct(self):
        store = CookieStore()
        assert store._key("g2.com", None) == "g2.com|direct"

    def test_different_proxies_different_keys(self):
        store = CookieStore()
        k1 = store._key("g2.com", "http://proxy1:8080")
        k2 = store._key("g2.com", "http://proxy2:9090")
        assert k1 != k2


# --- CookieStore.save_from_context ---


@pytest.mark.asyncio
class TestSaveFromContext:
    async def test_stores_cf_clearance_cookies(self):
        """Only cf_clearance, __cf_bm, __cflb cookies should be stored."""
        store = CookieStore()
        context = AsyncMock()
        context.cookies = AsyncMock(
            return_value=[
                {"name": "cf_clearance", "value": "val1", "domain": ".g2.com", "path": "/"},
                {"name": "__cf_bm", "value": "val2", "domain": ".g2.com", "path": "/"},
                {"name": "__cflb", "value": "val3", "domain": ".g2.com", "path": "/"},
                {"name": "session_id", "value": "ignored", "domain": ".g2.com", "path": "/"},
                {"name": "_ga", "value": "ignored", "domain": ".g2.com", "path": "/"},
            ]
        )

        await store.save_from_context(context, "g2.com")

        key = store._key("g2.com")
        stored = store._store[key]
        assert len(stored) == 3
        names = {c.name for c in stored}
        assert names == {"cf_clearance", "__cf_bm", "__cflb"}

    async def test_ignores_non_cloudflare_cookies(self):
        store = CookieStore()
        context = AsyncMock()
        context.cookies = AsyncMock(
            return_value=[
                {"name": "_ga", "value": "GA123", "domain": ".g2.com", "path": "/"},
                {"name": "session", "value": "sess", "domain": ".g2.com", "path": "/"},
            ]
        )

        await store.save_from_context(context, "g2.com")
        key = store._key("g2.com")
        assert store._store.get(key) == []

    async def test_stores_with_proxy_key(self):
        store = CookieStore()
        context = AsyncMock()
        context.cookies = AsyncMock(
            return_value=[
                {"name": "cf_clearance", "value": "val1", "domain": ".g2.com", "path": "/"},
            ]
        )

        await store.save_from_context(context, "g2.com", proxy_server="http://proxy:8080")
        key = store._key("g2.com", "http://proxy:8080")
        assert len(store._store[key]) == 1

    async def test_overwrites_previous_cookies_for_same_key(self):
        store = CookieStore()
        context1 = AsyncMock()
        context1.cookies = AsyncMock(
            return_value=[
                {"name": "cf_clearance", "value": "old", "domain": ".g2.com", "path": "/"},
            ]
        )
        context2 = AsyncMock()
        context2.cookies = AsyncMock(
            return_value=[
                {"name": "cf_clearance", "value": "new", "domain": ".g2.com", "path": "/"},
            ]
        )

        await store.save_from_context(context1, "g2.com")
        await store.save_from_context(context2, "g2.com")

        key = store._key("g2.com")
        assert len(store._store[key]) == 1
        assert store._store[key][0].value == "new"


# --- CookieStore.load_into_context ---


@pytest.mark.asyncio
class TestLoadIntoContext:
    async def test_loads_valid_cookies(self):
        store = CookieStore()
        key = store._key("g2.com")
        store._store[key] = [
            StoredCookie(name="cf_clearance", value="val1", domain=".g2.com"),
            StoredCookie(name="__cf_bm", value="val2", domain=".g2.com"),
        ]

        context = AsyncMock()
        loaded = await store.load_into_context(context, "g2.com")

        assert loaded == 2
        context.add_cookies.assert_called_once()
        cookies_arg = context.add_cookies.call_args[0][0]
        assert len(cookies_arg) == 2
        assert cookies_arg[0]["name"] == "cf_clearance"
        assert cookies_arg[0]["httpOnly"] is True
        assert cookies_arg[0]["secure"] is True

    async def test_skips_expired_cookies(self):
        store = CookieStore()
        key = store._key("g2.com")
        store._store[key] = [
            StoredCookie(
                name="cf_clearance",
                value="expired",
                domain=".g2.com",
                stored_at=time.time() - 2000,
                ttl_seconds=1500,
            ),
            StoredCookie(name="__cf_bm", value="valid", domain=".g2.com"),
        ]

        context = AsyncMock()
        loaded = await store.load_into_context(context, "g2.com")

        assert loaded == 1
        cookies_arg = context.add_cookies.call_args[0][0]
        assert cookies_arg[0]["name"] == "__cf_bm"

    async def test_returns_zero_when_no_cookies(self):
        store = CookieStore()
        context = AsyncMock()

        loaded = await store.load_into_context(context, "unknown.com")
        assert loaded == 0
        context.add_cookies.assert_not_called()

    async def test_returns_zero_when_all_expired(self):
        store = CookieStore()
        key = store._key("g2.com")
        store._store[key] = [
            StoredCookie(
                name="cf_clearance",
                value="expired",
                domain=".g2.com",
                stored_at=time.time() - 2000,
                ttl_seconds=1500,
            ),
        ]

        context = AsyncMock()
        loaded = await store.load_into_context(context, "g2.com")
        assert loaded == 0
        context.add_cookies.assert_not_called()

    async def test_loads_with_proxy_key(self):
        store = CookieStore()
        key = store._key("g2.com", "http://proxy:8080")
        store._store[key] = [
            StoredCookie(name="cf_clearance", value="val1", domain=".g2.com"),
        ]

        context = AsyncMock()
        loaded = await store.load_into_context(context, "g2.com", proxy_server="http://proxy:8080")
        assert loaded == 1

    async def test_does_not_load_from_different_proxy(self):
        store = CookieStore()
        key = store._key("g2.com", "http://proxy1:8080")
        store._store[key] = [
            StoredCookie(name="cf_clearance", value="val1", domain=".g2.com"),
        ]

        context = AsyncMock()
        loaded = await store.load_into_context(context, "g2.com", proxy_server="http://proxy2:9090")
        assert loaded == 0


# --- CookieStore.clear_expired ---


class TestClearExpired:
    def test_removes_expired_entries(self):
        store = CookieStore()
        key = store._key("g2.com")
        store._store[key] = [
            StoredCookie(
                name="cf_clearance",
                value="expired",
                domain=".g2.com",
                stored_at=time.time() - 2000,
                ttl_seconds=1500,
            ),
        ]

        store.clear_expired()
        assert key not in store._store

    def test_keeps_valid_entries(self):
        store = CookieStore()
        key = store._key("g2.com")
        store._store[key] = [
            StoredCookie(name="cf_clearance", value="valid", domain=".g2.com"),
        ]

        store.clear_expired()
        assert len(store._store[key]) == 1

    def test_mixed_expired_and_valid(self):
        store = CookieStore()
        key = store._key("g2.com")
        store._store[key] = [
            StoredCookie(
                name="cf_clearance",
                value="expired",
                domain=".g2.com",
                stored_at=time.time() - 2000,
                ttl_seconds=1500,
            ),
            StoredCookie(name="__cf_bm", value="valid", domain=".g2.com"),
        ]

        store.clear_expired()
        assert len(store._store[key]) == 1
        assert store._store[key][0].name == "__cf_bm"

    def test_removes_key_when_all_cookies_expired(self):
        store = CookieStore()
        key = store._key("g2.com")
        store._store[key] = [
            StoredCookie(
                name="cf_clearance",
                value="expired",
                domain=".g2.com",
                stored_at=time.time() - 2000,
                ttl_seconds=1500,
            ),
        ]

        store.clear_expired()
        assert key not in store._store


# --- get_cookie_store singleton ---


class TestGetCookieStore:
    def test_returns_same_instance(self):
        """get_cookie_store() should return the same singleton."""
        import app.cookie_store as cs
        cs._global_store = None  # reset

        store1 = get_cookie_store()
        store2 = get_cookie_store()
        assert store1 is store2

        cs._global_store = None  # cleanup

    def test_returns_cookie_store_instance(self):
        import app.cookie_store as cs
        cs._global_store = None

        store = get_cookie_store()
        assert isinstance(store, CookieStore)

        cs._global_store = None
