#!/usr/bin/env python3
"""Override tool for blackbox CLI.

Usage:
    python _override.py edit --reason "emergency hotfix"
    python _override.py commit --reason "tests broken upstream"

Creates a single-use override file that allows one blocked action to proceed.
"""
import json
import os
import sys
import hashlib
import tempfile
from datetime import datetime, timezone

# Allow importing _violations from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _violations import log_compliance


def main():
    args = sys.argv[1:]
    if len(args) < 1:
        print("Usage: blackbox override <action> --reason \"reason\"")
        print("  action: edit | commit")
        print("  --reason: why this override is needed")
        sys.exit(1)

    action = args[0]
    if action not in ("edit", "commit"):
        print(f"Unknown action: {action}. Must be 'edit' or 'commit'.")
        sys.exit(1)

    reason = "no reason given"
    for i, arg in enumerate(args):
        if arg == "--reason" and i + 1 < len(args):
            reason = args[i + 1]
            break

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    override_path = os.path.join(tempfile.gettempdir(), f"claude-override-{h}.json")

    override_data = {
        "action": action,
        "reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
        "uses": 1,
    }

    with open(override_path, "w", encoding="utf-8") as f:
        json.dump(override_data, f)

    # Log override to compliance
    log_compliance(proj_dir, {
        "type": "override_granted",
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "reason": reason,
        "project_hash": h,
    })

    print(f"Override granted: {action} (1 use)")
    print(f"Reason: {reason}")
    print(f"File: {override_path}")


if __name__ == "__main__":
    main()
