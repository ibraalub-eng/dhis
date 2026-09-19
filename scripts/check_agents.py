#!/usr/bin/env python3
"""Validate .agents/*.md agent definitions.

Every agent definition must have well-formed frontmatter so the coding
agent can discover it: a name matching the filename (kebab-case), a useful
description, a tools list containing only known tool names without
duplicates, and a non-trivial instruction body. Malformed definitions fail
this script, which CI runs on every push/PR.

Usage: python scripts/check_agents.py
"""
import re
import sys
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / ".agents"

# Tools known to the Freebuff/Codebuff agent runtime. Update this set when
# the runtime gains new tools (and keep agent definitions in sync).
KNOWN_TOOLS = {
    "read_files",
    "write_file",
    "str_replace",
    "run_terminal_command",
    "code_search",
    "glob",
    "list_directory",
    "write_todos",
    "register_preview",
    "preview_navigate",
    "preview_snapshot",
    "preview_evaluate",
    "preview_click",
    "preview_type",
    "preview_logs",
    "preview_screenshot",
}

MIN_DESCRIPTION_LEN = 40
MIN_BODY_CHARS = 400


def fail(agent: str, problems: list) -> None:
    print(f"FAIL {agent}:")
    for p in problems:
        print(f"  - {p}")


def check(path: Path) -> int:
    problems = []
    text = path.read_text(encoding="utf-8")
    stem = path.stem

    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not fm_match:
        fail(stem, ["missing frontmatter block (must start with '---' delimited YAML)"])
        return 1
    fm = fm_match.group(1)
    body = text[fm_match.end():]

    name = re.search(r"^name:\s*(\S.*)$", fm, re.M)
    if not name:
        problems.append("missing 'name'")
    else:
        value = name.group(1).strip()
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", value):
            problems.append(f"name '{value}' is not kebab-case")
        if value != stem:
            problems.append(f"name '{value}' does not match filename '{stem}'")

    desc = re.search(r"^description:\s*(\S.*)$", fm, re.M)
    if not desc:
        problems.append("missing 'description'")
    elif len(desc.group(1).strip()) < MIN_DESCRIPTION_LEN:
        problems.append(
            f"description too short ({len(desc.group(1).strip())} < {MIN_DESCRIPTION_LEN} chars)"
        )

    tools = re.search(r"^tools:\s*\[(.*?)\]\s*$", fm, re.M)
    if not tools:
        problems.append("missing 'tools' list (bracket format required)")
    else:
        tlist = [t.strip() for t in tools.group(1).split(",") if t.strip()]
        if not tlist:
            problems.append("empty 'tools' list")
        unknown = [t for t in tlist if t not in KNOWN_TOOLS]
        if unknown:
            problems.append(
                "unknown tool(s): "
                + ", ".join(unknown)
                + f" — known tools are: {', '.join(sorted(KNOWN_TOOLS))}"
            )
        dupes = sorted({t for t in tlist if tlist.count(t) > 1})
        if dupes:
            problems.append("duplicate tool(s): " + ", ".join(dupes))

    if len(body.strip()) < MIN_BODY_CHARS:
        problems.append(
            f"instruction body too short ({len(body.strip())} < {MIN_BODY_CHARS} chars)"
        )

    if problems:
        fail(stem, problems)
        return 1
    print(f"OK   {stem}")
    return 0


def main() -> int:
    if not AGENTS_DIR.is_dir():
        print(f"FAIL: agents directory not found: {AGENTS_DIR}")
        return 1
    files = sorted(AGENTS_DIR.glob("*.md"))
    if not files:
        print("FAIL: no agent definitions (*.md) found")
        return 1
    errors = sum(check(f) for f in files)
    print(f"\n{len(files) - errors}/{len(files)} agent definition(s) valid")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
