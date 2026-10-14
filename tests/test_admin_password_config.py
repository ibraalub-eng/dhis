"""US-06: admin password is never a shipped production default.

Production must refuse to start without a strong, non-default ADMIN_PASSWORD,
the dev/demo accounts must not be seeded in production, and no code path may
print the admin password to the logs.
"""
import os

import pytest

from app import config


class TestIsInsecureAdminPassword:
    @pytest.mark.parametrize("pw", [None, "", "   ", "short", "admin123",
                                    "admin", "password", "changeme", "123456"])
    def test_insecure_values(self, pw):
        assert config.is_insecure_admin_password(pw) is True

    @pytest.mark.parametrize("pw", [
        "correct horse battery staple",
        "Str0ng-Unique-Pass!",
        "a" * config.MIN_ADMIN_PASSWORD_LENGTH,
    ])
    def test_secure_values(self, pw):
        assert config.is_insecure_admin_password(pw) is False

    def test_legacy_default_is_rejected(self):
        assert config.is_insecure_admin_password(config.DEV_ADMIN_PASSWORD)


class TestValidateProductionAdminPassword:
    @pytest.mark.parametrize("pw", [None, "", "admin123", "short"])
    def test_rejects_missing_default_or_weak(self, pw):
        with pytest.raises(config.InsecureAdminPasswordError):
            config.validate_production_admin_password(pw)

    def test_accepts_strong_password(self):
        # Should not raise.
        config.validate_production_admin_password("a-very-strong-secret-pw")


class TestEnvironmentDetection:
    def test_explicit_app_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert config._detect_environment() == "production"

    def test_environment_alias(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert config._detect_environment() == "production"

    def test_managed_host_infers_production(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("RENDER", raising=False)
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
        monkeypatch.setenv("K_SERVICE", "health-ai")
        assert config._detect_environment() == "production"

    def test_defaults_to_development(self, monkeypatch):
        for var in ("APP_ENV", "ENVIRONMENT", "RENDER", "RENDER_GIT_COMMIT", "K_SERVICE"):
            monkeypatch.delenv(var, raising=False)
        assert config._detect_environment() == "development"


class TestResolveAdminPassword:
    def test_tests_fall_back_to_dev_default(self, monkeypatch):
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        assert config._resolve_admin_password() == config.DEV_ADMIN_PASSWORD

    def test_tests_honor_env_override(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", "explicit-test-pw")
        assert config._resolve_admin_password() == "explicit-test-pw"


class TestStartupSeeding:
    def test_dev_demo_users_seeded_in_development(self, db_session):
        import app.main as main
        from app.models import User

        main._ensure_admin_user(db_session)
        usernames = {u.username for u in db_session.query(User).all()}
        assert {"doctor", "viewer"} <= usernames

    def test_demo_users_not_seeded_in_production(self, db_session, monkeypatch):
        import app.main as main
        from app.models import User

        monkeypatch.setattr(main, "IS_PRODUCTION", True)
        main._ensure_admin_user(db_session)
        usernames = {u.username for u in db_session.query(User).all()}
        assert "doctor" not in usernames
        assert "viewer" not in usernames

    def test_startup_never_logs_admin_password(self, db_session, capsys, monkeypatch):
        import app.main as main

        monkeypatch.setattr(main, "IS_PRODUCTION", False)
        main._ensure_admin_user(db_session)
        captured = capsys.readouterr()
        assert config.ADMIN_PASSWORD not in (captured.out + captured.err)


class TestNoHardcodedPasswordInAppCode:
    def test_literal_only_lives_in_config(self):
        """`admin123` must not be hardcoded anywhere in app/ except the
        documented DEV_ADMIN_PASSWORD constant in config.py."""
        app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
        offenders = []
        for root, _dirs, files in os.walk(app_dir):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as f:
                    if "admin123" in f.read():
                        offenders.append(os.path.relpath(path, app_dir))
        assert offenders == [os.path.join("config.py")], (
            f"hardcoded dev password found outside app/config.py: {offenders}"
        )
