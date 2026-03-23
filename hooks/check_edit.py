#!/usr/bin/env python3
"""PreToolUse hook for Edit: BLOCK edits on files that haven't been read.

Outputs deny JSON if file was not read first (unless overridden).
Logs to compliance.jsonl either way.
"""
import sys
import json
import os
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

    fp = data.get("tool_input", {}).get("file_path", "")
    if not fp:
        return

    fp = os.path.normpath(fp).replace(os.sep, "/")

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    reads_file = os.path.join(tempfile.gettempdir(), f"claude-reads-{h}.txt")

    was_read = False
    if os.path.exists(reads_file):
        try:
            with open(reads_file, "r", encoding="utf-8") as f:
                read_paths = set(line.strip() for line in f if line.strip())
            was_read = fp in read_paths
        except Exception:
            pass

    was_overridden = False
    override_reason = None

    if not was_read:
        # Check for override
        override_reason = get_override(h, "edit")
        if override_reason:
            was_overridden = True

    # Log to compliance
    log_compliance(proj_dir, {
        "type": "edit_compliance",
        "ts": datetime.now(timezone.utc).isoformat(),
        "file": fp,
        "was_read_first": was_read,
        "was_overridden": was_overridden,
    })

    if not was_read and not was_overridden:
        # Increment violation counter
        count = increment_violation(h, "edit_without_read")

        # Output deny JSON to block the edit
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"BLOCKED: Cannot edit {fp} -- read it first. (violation #{count})",
            }
        }
        print(json.dumps(result))


if __name__ == "__main__":
    main()
