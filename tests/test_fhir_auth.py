"""SMART-on-FHIR auth helper tests — PKCE, signed state cookies, token exchange.

Covers the spec section 17 coverage gap (FHIR OAuth/PKCE flow). `fhir/*` is
excluded from the coverage config, so the PKCE/state/token helpers — which guard
the OAuth callback against CSRF and tampering — had no dedicated tests.
"""
import time

import httpx
import pytest
import respx
from itsdangerous import URLSafeTimedSerializer

from fhir import auth


# ── PKCE ─────────────────────────────────────────────────────────────────────

class TestPkce:
    def test_pair_is_url_safe_and_unpadded(self):
        verifier, challenge = auth.generate_pkce_pair()
        assert verifier and challenge
        assert verifier != challenge
        # base64url without padding — required by RFC 7636
        assert "=" not in verifier and "=" not in challenge
        assert "+" not in challenge and "/" not in challenge

    def test_pairs_are_random(self):
        v1, _ = auth.generate_pkce_pair()
        v2, _ = auth.generate_pkce_pair()
        assert v1 != v2

    def test_challenge_is_s256_of_verifier(self):
        import base64
        import hashlib
        verifier, challenge = auth.generate_pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert challenge == expected

    def test_state_is_unique_and_long(self):
        s1, s2 = auth.generate_secure_state(), auth.generate_secure_state()
        assert s1 != s2
        assert len(s1) >= 32


# ── Signed state / session cookies ───────────────────────────────────────────

class TestCookies:
    def test_state_cookie_roundtrip(self):
        token = auth.encode_fhir_cookie({"state": "xyz", "verifier": "v1"})
        decoded = auth.decode_fhir_state_cookie(token)
        assert decoded == {"state": "xyz", "verifier": "v1"}

    def test_tampered_cookie_rejected(self):
        token = auth.encode_fhir_cookie({"state": "xyz"})
        assert auth.decode_fhir_state_cookie(token + "tamper") is None

    def test_garbage_cookie_rejected(self):
        assert auth.decode_fhir_state_cookie("not-a-real-token") is None

    def test_cookie_signed_with_other_key_rejected(self):
        forged = URLSafeTimedSerializer("a-totally-different-key", salt="fhir-v1")
        token = forged.dumps({"state": "evil"})
        assert auth.decode_fhir_state_cookie(token) is None

    def test_expired_state_cookie_rejected(self, monkeypatch):
        token = auth.encode_fhir_cookie({"state": "xyz"})
        # Advance time beyond the 5-minute state TTL.
        real_time = time.time
        monkeypatch.setattr(time, "time",
                            lambda: real_time() + auth.FHIR_STATE_TTL + 10)
        assert auth.decode_fhir_state_cookie(token) is None


# ── Token refresh timing ─────────────────────────────────────────────────────

class TestNeedsRefresh:
    def test_expired_token_needs_refresh(self):
        assert auth.needs_refresh(time.time() - 10) is True

    def test_token_within_buffer_needs_refresh(self):
        assert auth.needs_refresh(time.time() + auth.TOKEN_REFRESH_BUFFER - 5) is True

    def test_fresh_token_does_not_need_refresh(self):
        assert auth.needs_refresh(time.time() + 3600) is False


# ── Token exchange / refresh (HTTP mocked) ───────────────────────────────────

class TestTokenExchange:
    @respx.mock
    async def test_exchange_sends_pkce_verifier(self):
        route = respx.post("https://ehr.example/token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "AT", "refresh_token": "RT", "expires_in": 3600}))
        result = await auth.exchange_code_for_token(
            code="code123", token_endpoint="https://ehr.example/token",
            client_id="client-1", redirect_uri="https://app/cb", code_verifier="ver")
        assert result["access_token"] == "AT"
        body = route.calls.last.request.content.decode()
        assert "code_verifier=ver" in body
        assert "grant_type=authorization_code" in body

    @respx.mock
    async def test_confidential_client_uses_basic_auth(self):
        route = respx.post("https://ehr.example/token").mock(
            return_value=httpx.Response(200, json={"access_token": "AT"}))
        await auth.exchange_code_for_token(
            code="c", token_endpoint="https://ehr.example/token",
            client_id="cid", redirect_uri="https://app/cb", client_secret="shh")
        assert route.calls.last.request.headers.get("Authorization", "").startswith("Basic ")

    @respx.mock
    async def test_exchange_propagates_http_error(self):
        respx.post("https://ehr.example/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(httpx.HTTPStatusError):
            await auth.exchange_code_for_token(
                code="bad", token_endpoint="https://ehr.example/token",
                client_id="cid", redirect_uri="https://app/cb")

    @respx.mock
    async def test_refresh_sends_refresh_grant(self):
        route = respx.post("https://ehr.example/token").mock(
            return_value=httpx.Response(200, json={"access_token": "AT2"}))
        result = await auth.refresh_access_token(
            refresh_token="RT", token_endpoint="https://ehr.example/token",
            client_id="cid")
        assert result["access_token"] == "AT2"
        body = route.calls.last.request.content.decode()
        assert "grant_type=refresh_token" in body
        assert "refresh_token=RT" in body
