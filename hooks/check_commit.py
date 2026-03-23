#!/usr/bin/env python3
"""PreToolUse hook for Bash: check if tests ran before git commit."""
import sys
import json
import os
import re
import hashlib
import tempfile
from datetime import datetime, timezone

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd or not re.search(r'\bgit\s+commit\b', cmd):
        return

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")

    tests_ran = os.path.exists(tested_file)

    sessions_dir = os.path.join(proj_dir, ".claude", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    compliance = os.path.join(sessions_dir, "compliance.jsonl")

    entry = {
        "type": "commit_compliance",
        "ts": datetime.now(timezone.utc).isoformat(),
        "command": cmd[:200],
        "tests_ran_first": tests_ran,
    }
    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

if __name__ == "__main__":
    main()
