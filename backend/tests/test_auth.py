"""
Tests for server.py's request auth guard.

These matter more than most: `_require_token` is the only thing standing
between a Cloudflare-tunnelled backend and an anonymous caller who can start
live trading, read the MT5 login and overwrite the MT5 password. Every case
below is a rule someone could plausibly "simplify" away later.

The guard accepts two credentials — the .env API_TOKEN, or the activated
license key (so a single-user install needs no second secret). Tests patch
both rather than reading the real .env, so they behave identically on a
machine that has never been activated.
"""
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

import config
import server

TOKEN = "test-api-token-abcdefghijklmnop"
LICENSE = "MOJALEFA-1234"
OTHER_LICENSE = "MOJALEFA-9999"


def call(path: str, sent: str | None, stored_license: str, api_token: str = TOKEN) -> bool:
    """Run the guard. Returns True if allowed, False on 401."""
    request = Mock()
    request.url.path = path
    with patch.object(config, "API_TOKEN", api_token), \
         patch.object(server.bridge, "activated_license_key", return_value=stored_license):
        try:
            server._require_token(request, sent)
            return True
        except HTTPException as exc:
            assert exc.status_code == 401
            return False


class TestLocalOnlyMode:
    def test_no_api_token_configured_allows_everything(self):
        # Unchanged behaviour: an empty API_TOKEN means local-only, and
        # server.py's __main__ guard already refuses to bind off-loopback then.
        assert call("/bot/start", None, "", api_token="")
        assert call("/settings", None, LICENSE, api_token="")


class TestPublicPaths:
    @pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json", "/redoc", "/purchase/request"])
    def test_always_reachable_without_credentials(self, path):
        # The supervisor and tunnel health check need these before they have
        # any credential.
        assert call(path, None, LICENSE)


class TestBootstrap:
    def test_validate_is_reachable_before_activation(self):
        # First run: there is no credential the operator could possibly send,
        # so this must be reachable or the product cannot be set up at all.
        assert call("/license/validate", None, "")

    def test_only_validate_is_exempt_before_activation(self):
        # The bootstrap hole must be exactly one endpoint wide.
        assert not call("/stats", None, "")
        assert not call("/bot/start", None, "")
        assert not call("/settings", None, "")

    def test_exemption_disappears_once_activated(self):
        # THE escalation guard. Without this, anyone holding any valid license
        # key could POST it to an activated backend, overwrite the stored key,
        # and mint themselves a credential that passes this check.
        assert not call("/license/validate", None, LICENSE)
        assert not call("/license/validate", OTHER_LICENSE, LICENSE)

    def test_reactivating_with_the_current_key_still_works(self):
        # Changing licenses requires already holding a valid credential.
        assert call("/license/validate", LICENSE, LICENSE)
        assert call("/license/validate", TOKEN, LICENSE)


class TestCredentials:
    def test_license_key_authenticates_every_route(self):
        # The whole point: the key typed on the Activation screen is enough.
        for path in ("/stats", "/bot/start", "/settings", "/trades"):
            assert call(path, LICENSE, LICENSE), path

    def test_license_key_length_mismatch_with_api_token_still_authenticates(self):
        # secrets.compare_digest raises if the strings differ in length. The
        # license key is 13 chars and API_TOKEN is not, so the guard must
        # skip the token compare instead of 500ing every dashboard poll.
        assert call("/stats", LICENSE, LICENSE)

    def test_api_token_still_authenticates(self):
        # Accepting the license key must not remove the original credential.
        for path in ("/stats", "/bot/start", "/settings"):
            assert call(path, TOKEN, LICENSE), path

    def test_rejects_wrong_or_missing_credentials(self):
        assert not call("/stats", None, LICENSE)
        assert not call("/stats", "", LICENSE)
        assert not call("/stats", "wrong", LICENSE)
        assert not call("/stats", OTHER_LICENSE, LICENSE)

    def test_license_key_is_not_accepted_when_none_is_stored(self):
        # An unactivated backend must not accept a guessed key as a credential.
        assert not call("/stats", LICENSE, "")

    def test_near_miss_credentials_are_rejected(self):
        # Guards against a prefix/substring comparison creeping in.
        assert not call("/stats", TOKEN[:-1], LICENSE)
        assert not call("/stats", TOKEN + "x", LICENSE)
        assert not call("/stats", LICENSE.lower(), LICENSE)


class TestBridgeHelper:
    def test_unreadable_license_file_fails_closed(self):
        # Returning "" makes the guard fall back to requiring API_TOKEN rather
        # than silently accepting anything.
        with patch.object(server.bridge, "check_license", side_effect=OSError("boom")):
            assert server.bridge.activated_license_key() == ""

    def test_invalid_stored_license_is_not_a_credential(self):
        with patch.object(server.bridge, "check_license", return_value={"ok": False, "key": "junk"}):
            assert server.bridge.activated_license_key() == ""
