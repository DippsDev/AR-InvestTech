"""Tenant gateway: one public site, many VPS backends.

A second customer's license key must never be handled as this machine's
credential, and a key that belongs here must never be proxied away.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import config
import server
from bridge import BotBridge, _remote_backend_url

LICENSE = "MOJALEFA-1234"
OTHER = "MOJALEFA-9999"
TOKEN = "test-api-token-abcdefghijklmnop"
TENANT_URL = "http://10.0.0.9:8000"


class TestRemoteUrlHelper:
    def test_blank_or_self_is_local(self):
        assert _remote_backend_url(None) is None
        assert _remote_backend_url("") is None
        assert _remote_backend_url("https://bot.ar-investech.uk") is None
        assert _remote_backend_url("https://bot.ar-investech.uk/") is None
        assert _remote_backend_url("http://127.0.0.1:8000") is None

    def test_other_machine_is_remote(self):
        assert _remote_backend_url(TENANT_URL) == TENANT_URL
        assert _remote_backend_url(TENANT_URL + "/") == TENANT_URL

    def test_rejects_non_http(self):
        assert _remote_backend_url("javascript:alert(1)") is None
        assert _remote_backend_url("/relative") is None


class TestBackendUrlLookup:
    def setup_method(self):
        self.bridge = BotBridge()
        self.bridge._backend_url_cache.clear()

    def test_api_token_is_never_looked_up(self):
        with patch.object(config, "API_TOKEN", TOKEN):
            assert self.bridge.remote_backend_url_for_token(TOKEN) is None

    def test_non_license_token_is_local(self):
        assert self.bridge.remote_backend_url_for_token("not-a-key") is None
        assert self.bridge.remote_backend_url_for_token("") is None

    def test_returns_tenant_url(self):
        with patch.object(self.bridge, "_lookup_remote_backend_url", return_value=TENANT_URL):
            assert self.bridge.remote_backend_url_for_token(OTHER) == TENANT_URL

    def test_empty_backend_url_stays_local(self):
        with patch.object(self.bridge, "_lookup_remote_backend_url", return_value=None):
            assert self.bridge.remote_backend_url_for_token(LICENSE) is None

    def test_caches_lookup(self):
        lookup = Mock(return_value=TENANT_URL)
        with patch.object(self.bridge, "_lookup_remote_backend_url", lookup):
            assert self.bridge.remote_backend_url_for_token(OTHER) == TENANT_URL
            assert self.bridge.remote_backend_url_for_token(OTHER) == TENANT_URL
        lookup.assert_called_once_with(OTHER)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server.bridge, "resume_on_startup", lambda: None)
    monkeypatch.setattr(server.bridge, "shutdown", lambda: None)
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    with TestClient(server.app, raise_server_exceptions=True) as test_client:
        yield test_client


class TestGatewayProxy:
    def test_health_is_never_proxied(self, client, monkeypatch):
        monkeypatch.setattr(
            server.bridge, "remote_backend_url_for_token",
            lambda token: TENANT_URL,
        )
        called = {"proxy": False}

        async def boom(*_args, **_kwargs):
            called["proxy"] = True
            raise AssertionError("health must not be proxied")

        monkeypatch.setattr(server, "proxy_tenant_request", boom)
        r = client.get("/health", headers={"X-API-Token": OTHER})
        assert r.status_code == 200
        assert called["proxy"] is False

    def test_tenant_key_is_proxied(self, client, monkeypatch):
        monkeypatch.setattr(
            server.bridge, "remote_backend_url_for_token",
            lambda token: TENANT_URL if token == OTHER else None,
        )

        async def fake_proxy(request: Request, target: str):
            assert target == TENANT_URL
            assert request.url.path == "/stats"
            return server.JSONResponse({"running": True, "proxied": True})

        monkeypatch.setattr(server, "proxy_tenant_request", fake_proxy)
        r = client.get("/stats", headers={"X-API-Token": OTHER})
        assert r.status_code == 200
        assert r.json()["proxied"] is True

    def test_local_key_is_not_proxied(self, client, monkeypatch):
        monkeypatch.setattr(
            server.bridge, "remote_backend_url_for_token",
            lambda token: None,
        )
        monkeypatch.setattr(server.bridge, "activated_license_key", lambda: LICENSE)
        monkeypatch.setattr(server.bridge, "get_stats", lambda: {"running": False})
        called = {"proxy": False}

        async def boom(*_args, **_kwargs):
            called["proxy"] = True
            raise AssertionError("local keys must not be proxied")

        monkeypatch.setattr(server, "proxy_tenant_request", boom)
        r = client.get("/stats", headers={"X-API-Token": LICENSE})
        assert called["proxy"] is False
        assert r.status_code == 200
        assert r.json()["running"] is False
