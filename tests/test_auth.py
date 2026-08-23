"""Tests for auth security utilities, models, and dependencies."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.models import User, Role, Permission, RefreshToken, user_roles, role_permissions


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


# --- Model tests ---

@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_permission(db_session):
    p = Permission(codename="dashboard.read", description="Read dashboard")
    db_session.add(p)
    db_session.commit()
    assert db_session.query(Permission).filter_by(codename="dashboard.read").count() == 1


def test_create_role_with_permissions(db_session):
    p1 = Permission(codename="dashboard.read")
    p2 = Permission(codename="data.upload")
    role = Role(name="doctor", description="Doctor role", permissions=[p1, p2])
    db_session.add(role)
    db_session.commit()
    fetched = db_session.query(Role).filter_by(name="doctor").first()
    assert len(fetched.permissions) == 2
    assert {p.codename for p in fetched.permissions} == {"dashboard.read", "data.upload"}


def test_create_user_with_role(db_session):
    p = Permission(codename="dashboard.read")
    role = Role(name="viewer", permissions=[p])
    user = User(
        username="testuser", email="test@test.com", full_name="Test User",
        password_hash=hash_password("pass123"), roles=[role],
    )
    db_session.add(user)
    db_session.commit()
    fetched = db_session.query(User).filter_by(username="testuser").first()
    assert fetched is not None
    assert len(fetched.roles) == 1
    assert fetched.roles[0].name == "viewer"


def test_refresh_token_model(db_session):
    from datetime import datetime
    user = User(username="u1", email="u1@test.com", full_name="U1", password_hash=hash_password("p"))
    db_session.add(user)
    db_session.commit()
    rt = RefreshToken(user_id=user.id, token_jti="abc123", expires_at=datetime(2026, 12, 31))
    db_session.add(rt)
    db_session.commit()
    assert db_session.query(RefreshToken).filter_by(token_jti="abc123").count() == 1
