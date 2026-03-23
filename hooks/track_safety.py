#!/usr/bin/env python3
"""PostToolUse hook for Bash: record destructive command catches."""
import sys
import json
import os
import re
import hashlib
from datetime import datetime, timezone

DANGEROUS_PATTERNS = [
    (r'rm\s+-rf', 'rm -rf'),
    (r'DROP\s+TABLE', 'DROP TABLE'),
    (r'git\s+push\s+--force', 'git push --force'),
    (r'git\s+reset\s+--hard', 'git reset --hard'),
    (r'pm2\s+delete', 'pm2 delete'),
    (r'ssh\s+.*\brm\b', 'ssh+rm (remote deletion)'),
]

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        return

    for pattern, name in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd, re.I):
            proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
            sessions_dir = os.path.join(proj_dir, ".claude", "sessions")
            os.makedirs(sessions_dir, exist_ok=True)
            compliance = os.path.join(sessions_dir, "compliance.jsonl")

            entry = {
                "type": "safety_trigger",
                "ts": datetime.now(timezone.utc).isoformat(),
                "command": cmd[:200],
                "pattern": name,
            }
            with open(compliance, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            return

if __name__ == "__main__":
    main()
