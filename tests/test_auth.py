"""Tests for auth security utilities and dependencies."""
import pytest
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)


def test_hash_and_verify_password():
    hashed = hash_password("testpass123")
    assert hashed != "testpass123"
    assert verify_password("testpass123", hashed)
    assert not verify_password("wrongpass", hashed)


def test_create_and_decode_access_token():
    token = create_access_token(user_id=1, roles=["admin"], permissions=["dashboard.read"])
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "1"
    assert payload["roles"] == ["admin"]
    assert payload["permissions"] == ["dashboard.read"]
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    token, jti, expires_at = create_refresh_token(user_id=42)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["jti"] == jti
    assert payload["type"] == "refresh"


def test_decode_invalid_token_returns_none():
    assert decode_token("garbage.token.value") is None


def test_decode_expired_token():
    """Manually create an expired token."""
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.config import JWT_SECRET, JWT_ALGORITHM

    payload = {
        "sub": "1",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "type": "access",
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    assert decode_token(token) is None
