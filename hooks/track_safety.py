#!/usr/bin/env python3
"""PostToolUse hook for Bash: track destructive commands with escalation.

1st occurrence -> warning
3rd occurrence -> severity=block (logged)
Tracks violation count per session via shared violations module.
"""
import sys
import json
import os
import re
import hashlib
from datetime import datetime, timezone

# Allow importing _violations from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _violations import increment_violation, get_violations, log_compliance

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
            h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]

            # Increment violation count
            count = increment_violation(h, "safety_trigger")

            # Determine severity based on count
            if count >= 3:
                severity = "block"
            else:
                severity = "warning"

            log_compliance(proj_dir, {
                "type": "safety_trigger",
                "ts": datetime.now(timezone.utc).isoformat(),
                "command": cmd[:200],
                "pattern": name,
                "severity": severity,
                "occurrence": count,
            })
            return


if __name__ == "__main__":
    main()
