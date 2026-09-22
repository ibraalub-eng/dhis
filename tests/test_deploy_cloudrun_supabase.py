"""Guards for deploy-cloudrun-supabase.sh (Cloud Run + free Supabase Postgres).

The script is the documented $0/month deploy path (docs/INSTALL_RUN_GUIDE.md);
these checks keep it deployable: it must validate the Supabase POOLER URL
(the direct host is IPv6-only and unreachable from Cloud Run), refuse
transaction-mode port 6543, and wire the three secrets (DATABASE_URL,
JWT_SECRET, ADMIN_PASSWORD) the Cloud Build pipeline alone doesn't set.
"""
import os

SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "deploy-cloudrun-supabase.sh"
)


def _read():
    with open(SCRIPT, encoding="utf-8") as f:
        return f.read()


def test_rejects_direct_supabase_host():
    """Supabase direct db.<ref>.supabase.co is IPv6-only → Cloud Run (IPv4)
    can't connect; the script must demand the pooler host."""
    body = _read()
    assert "pooler" in body
    assert "supabase.co" in body or "supabase.com" in body
    assert "IPv6" in body


def test_rejects_transaction_mode_port():
    body = _read()
    assert ":6543/" in body, "must detect transaction-mode port 6543"
    assert "5432" in body, "session pooler (5432) is the tested path"


def test_wires_all_three_secrets():
    """DATABASE_URL alone leaves JWT_SECRET and ADMIN_PASSWORD on dev
    defaults — a real hole on a public URL."""
    body = _read()
    for secret in ("database-url", "jwt-secret", "admin-password"):
        assert secret in body
    assert (
        "JWT_SECRET=jwt-secret:latest" in body
        and "ADMIN_PASSWORD=admin-password:latest" in body
    )


def test_deploy_flags_match_cloudsql_script():
    """Keep the free-tier-safe Cloud Run flags in sync with deploy-cloudrun.sh:
    min-instances 0 (pay only per request), bounded max, 1Gi memory."""
    body = _read()
    for flag in (
        "--min-instances 0",
        "--max-instances 3",
        "--memory 1Gi",
        "--allow-unauthenticated",
        "--set-secrets",
    ):
        assert flag in body


def test_builds_and_smoke_checks_like_cloudsql_script():
    body = _read()
    assert "gcloud builds submit" in body
    assert "/health" in body, "must smoke-test the deployed service"


def test_script_is_valid_bash():
    import subprocess

    result = subprocess.run(
        ["bash", "-n", SCRIPT], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
