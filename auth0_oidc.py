"""Auth0 OIDC integration — enterprise SSO via SAML/OIDC connectors.

Auth0 acts as the broker: it connects to enterprise IdPs (Okta, Azure AD,
Google Workspace, ADFS) via SAML or OIDC. The app only speaks OIDC to Auth0;
the SAML complexity is handled entirely on the Auth0 side.

Required environment variables:
    AUTH0_DOMAIN        e.g. your-tenant.auth0.com
    AUTH0_CLIENT_ID
    AUTH0_CLIENT_SECRET
    AUTH0_CALLBACK_URL  e.g. https://yourapp.vercel.app/auth/sso/callback
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import urllib.parse

import httpx


def is_configured() -> bool:
    return bool(
        os.getenv("AUTH0_DOMAIN")
        and os.getenv("AUTH0_CLIENT_ID")
        and os.getenv("AUTH0_CLIENT_SECRET")
    )


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorize_url(state: str, code_challenge: str, redirect_uri: str) -> str:
    params = {
        "response_type": "code",
        "client_id": os.getenv("AUTH0_CLIENT_ID", ""),
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"https://{os.getenv('AUTH0_DOMAIN', '')}/authorize?" + urllib.parse.urlencode(params)


async def exchange_code(code: str, code_verifier: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://{os.getenv('AUTH0_DOMAIN', '')}/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": os.getenv("AUTH0_CLIENT_ID", ""),
                "client_secret": os.getenv("AUTH0_CLIENT_SECRET", ""),
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def get_userinfo(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://{os.getenv('AUTH0_DOMAIN', '')}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
