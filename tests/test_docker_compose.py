"""Guards for the one-command Docker Compose stack (docker-compose.yml).

The app+db stack is the documented install path (docs/INSTALL_RUN_GUIDE.md
§4.1); these checks keep it runnable: services wired, healthchecks present,
and no host-referencing DATABASE_URL leaked into the container.
"""
import os

import yaml


def _compose():
    path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_compose_has_db_and_app_services():
    compose = _compose()
    services = compose.get("services", {})
    assert "db" in services and "app" in services


def test_db_is_postgres_with_healthcheck():
    db = _compose()["services"]["db"]
    assert str(db.get("image", "")).startswith("postgres:")
    assert "healthcheck" in db, "app start is gated on db health"
    assert db.get("volumes"), "pgdata volume must persist database files"


def test_app_builds_from_dockerfile_and_waits_for_db():
    app = _compose()["services"]["app"]
    assert app.get("build", {}).get("dockerfile") == "Dockerfile"
    assert app.get("depends_on", {}).get("db", {}).get("condition") == "service_healthy"


def test_app_database_url_uses_compose_host_not_localhost():
    """Inside the compose network the DB host is the service name `db`;
    a localhost URL would point at the container itself and show the
    setup-instructions page forever."""
    app = _compose()["services"]["app"]
    url = app.get("environment", {}).get("DATABASE_URL", "")
    assert "@db:5432/" in url
    assert "localhost" not in url and "127.0.0.1" not in url


def test_app_healthcheck_hits_health_endpoint():
    app = _compose()["services"]["app"]
    test = app.get("healthcheck", {}).get("test", [])
    assert any("/health" in str(part) for part in test)


def test_dockerignore_never_ships_env():
    """Secrets guard: .env must stay out of the image build context."""
    path = os.path.join(os.path.dirname(__file__), "..", ".dockerignore")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert ".env" in content
    # Local venvs/tooling excluded so build contexts stay small.
    assert ".venv" in content
