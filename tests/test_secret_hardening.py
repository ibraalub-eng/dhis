"""Secrets / CORS hardening regression tests (Batch 5).

- `app.config._secret` must never fall back to a hardcoded credential when
  the env var is missing: it uses the pytest dev default (or a random token),
  not a shipped production secret.
- The CORS middleware must not combine a wildcard origin with credentials.
"""
import sys

from starlette.middleware.cors import CORSMiddleware

from app import config
from app.main import app


def _cors_kwargs():
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return mw.kwargs
    raise AssertionError("CORSMiddleware not registered")


class TestSecretHelper:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("SCOPE_TEST_SECRET", "explicit-value")
        assert config._secret("SCOPE_TEST_SECRET") == "explicit-value"

    def test_pytest_branch_uses_dev_default(self, monkeypatch):
        monkeypatch.delenv("SCOPE_TEST_SECRET", raising=False)
        assert "pytest" in sys.modules
        assert config._secret("SCOPE_TEST_SECRET", dev_default="dev-default") == "dev-default"

    def test_pytest_branch_without_default_is_random(self, monkeypatch):
        monkeypatch.delenv("SCOPE_TEST_SECRET", raising=False)
        a = config._secret("SCOPE_TEST_SECRET")
        b = config._secret("SCOPE_TEST_SECRET")
        assert a and b and a != b

    def test_non_pytest_missing_var_is_random_not_default(self, monkeypatch):
        monkeypatch.delenv("SCOPE_TEST_SECRET", raising=False)
        monkeypatch.delenv("TESTING", raising=False)
        saved = sys.modules.pop("pytest", None)
        try:
            a = config._secret("SCOPE_TEST_SECRET")
            b = config._secret("SCOPE_TEST_SECRET")
        finally:
            if saved is not None:
                sys.modules["pytest"] = saved
        assert a and b and a != b

    def test_non_pytest_dev_default_is_warned_default(self, monkeypatch):
        monkeypatch.delenv("SCOPE_TEST_SECRET", raising=False)
        monkeypatch.delenv("TESTING", raising=False)
        saved = sys.modules.pop("pytest", None)
        try:
            val = config._secret("SCOPE_TEST_SECRET", dev_default="dev-only")
        finally:
            if saved is not None:
                sys.modules["pytest"] = saved
        assert val == "dev-only"


class TestConfigSecrets:
    def test_jwt_secret_present(self):
        assert isinstance(config.JWT_SECRET, str) and config.JWT_SECRET

    def test_unset_secret_has_no_legacy_default(self):
        assert config._secret("SCOPE_UNSET_XYZ") not in ("", "admin123")


class TestCorsHardening:
    def test_no_wildcard_origin_with_credentials(self):
        kwargs = _cors_kwargs()
        origins = kwargs["allow_origins"]
        if "*" in origins:
            assert kwargs["allow_credentials"] is False
        else:
            assert origins  # explicit origins
