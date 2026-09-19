"""CI parity: the agent-definition linter must pass on this checkout.

scripts/check_agents.py is also a dedicated GitHub Actions job; this test
makes the full local suite (pytest) catch the same failures before push.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_agents.py"


def test_agent_definitions_pass_linter():
    assert SCRIPT.is_file(), "scripts/check_agents.py is missing"
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, (
        "agent definitions failed linting:\n"
        + result.stdout
        + result.stderr
    )


def test_linter_rejects_malformed_definition(tmp_path):
    """The linter must actually fail a broken agent file (self-test)."""
    broken = tmp_path / "broken-agent.md"
    broken.write_text(
        "---\n"
        "name: TestAgent\n"
        "description: short\n"
        "tools: [read_files, made_up_tool, read_files]\n"
        "---\n"
        "\n"
        "Too short body.\n",
        encoding="utf-8",
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_agents", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Re-implement the file-reading so we can point the checker at tmp_path
    original = mod.AGENTS_DIR
    mod.AGENTS_DIR = tmp_path
    try:
        rc = mod.main()
    finally:
        mod.AGENTS_DIR = original
    assert rc == 1, "linter accepted a malformed agent definition"
