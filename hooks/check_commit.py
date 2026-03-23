#!/usr/bin/env python3
"""PreToolUse hook for Bash: BLOCK git commits if tests haven't passed.

Outputs deny JSON if tests didn't pass (unless overridden).
Logs to compliance.jsonl either way.
"""
import sys
import json
import os
import re
import hashlib
import tempfile
from datetime import datetime, timezone

# Allow importing _violations from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _violations import get_override, increment_violation, log_compliance


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

    tests_passed = False
    if os.path.exists(tested_file):
        try:
            with open(tested_file, "r") as f:
                content = f.read().strip()
            tests_passed = content == "passed"
        except Exception:
            pass

    was_overridden = False
    override_reason = None

    if not tests_passed:
        override_reason = get_override(h, "commit")
        if override_reason:
            was_overridden = True

    # Log to compliance
    log_compliance(proj_dir, {
        "type": "commit_compliance",
        "ts": datetime.now(timezone.utc).isoformat(),
        "command": cmd[:200],
        "tests_passed_first": tests_passed,
        "was_overridden": was_overridden,
    })

    if not tests_passed and not was_overridden:
        count = increment_violation(h, "commit_without_test")

        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"BLOCKED: Cannot commit without passing tests first. (violation #{count})",
            }
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
