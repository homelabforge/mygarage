"""The `iss` claim is validated against the DISCOVERY document's issuer, not the
issuer URL stored in settings.

Regression (2026-07-20): Rauthy reports `issuer` with a trailing slash
(`https://id.example.com/auth/v1/`), while `routes/oidc.py` rstrips the trailing
slash before persisting. The stored value therefore could never equal the token's
`iss`, and every OIDC login failed with `invalid_claim: Invalid claim: 'iss'` —
surfacing to the user as `{"detail":"Failed to verify ID token"}`.

OIDC Core §3.1.3.7(2) requires `iss` to exactly match the provider's Issuer
Identifier, which is what the metadata document reports — so discovery is the
correct source, and the stored setting is only a fallback.
"""

import time
from unittest.mock import patch

import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from app.services.oidc.tokens import verify_id_token

ISSUER_DISCOVERY = "https://id.example.com/auth/v1/"  # what Rauthy reports
ISSUER_STORED = "https://id.example.com/auth/v1"  # what rstrip("/") leaves behind
CLIENT_ID = "mygarage"
NONCE = "test-nonce"
JWKS_URI = "https://id.example.com/auth/v1/oidc/certs"


@pytest.fixture
def signing_key() -> RSAKey:
    """A throwaway RSA key standing in for the provider's signing key."""
    return RSAKey.generate_key(2048, parameters={"kid": "test-key-1"})


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient so the JWKS fetch stays offline."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(self._payload)


def _make_id_token(key: RSAKey, issuer: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"alg": "RS256", "kid": key.kid},
        {
            "iss": issuer,
            "aud": CLIENT_ID,
            "nonce": NONCE,
            "sub": "user-1",
            "iat": now,
            "exp": now + 300,
        },
        key,
    )


async def _verify(key: RSAKey, token_issuer: str, metadata: dict, config: dict) -> dict | None:
    jwks = KeySet([key]).as_dict(private=False)
    with (
        patch("app.services.oidc.tokens.validate_oidc_url", return_value=None),
        patch(
            "app.services.oidc.tokens.httpx.AsyncClient",
            lambda *a, **kw: _FakeAsyncClient(jwks),
        ),
    ):
        return await verify_id_token(_make_id_token(key, token_issuer), config, metadata, NONCE)


async def test_trailing_slash_issuer_verifies_against_discovery(signing_key: RSAKey) -> None:
    """The exact production failure: token `iss` has the slash, the stored setting doesn't."""
    claims = await _verify(
        signing_key,
        token_issuer=ISSUER_DISCOVERY,
        metadata={"issuer": ISSUER_DISCOVERY, "jwks_uri": JWKS_URI},
        config={"issuer_url": ISSUER_STORED, "client_id": CLIENT_ID},
    )

    assert claims is not None, "trailing-slash issuer must verify (regression: it did not)"
    assert claims["sub"] == "user-1"


async def test_issuer_mismatch_still_rejected(signing_key: RSAKey) -> None:
    """Guard against fixing the slash by weakening the check: a genuinely wrong
    issuer must still fail, even when it matches the stored setting."""
    claims = await _verify(
        signing_key,
        token_issuer="https://evil.example.com/auth/v1/",
        metadata={"issuer": ISSUER_DISCOVERY, "jwks_uri": JWKS_URI},
        config={"issuer_url": "https://evil.example.com/auth/v1", "client_id": CLIENT_ID},
    )

    assert claims is None


async def test_falls_back_to_stored_issuer_when_metadata_omits_it(
    signing_key: RSAKey,
) -> None:
    """A provider that omits `issuer` from its metadata still works off the setting."""
    claims = await _verify(
        signing_key,
        token_issuer=ISSUER_STORED,
        metadata={"jwks_uri": JWKS_URI},
        config={"issuer_url": ISSUER_STORED, "client_id": CLIENT_ID},
    )

    assert claims is not None
    assert claims["sub"] == "user-1"
