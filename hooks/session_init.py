#!/usr/bin/env python3
"""SessionStart hook: reset tracking files, tag session ID."""
import os
import sys
import json
import hashlib
import tempfile
from datetime import datetime, timezone


def main():
    # Read session_id from stdin
    session_id = ""
    try:
        data = json.load(sys.stdin)
        session_id = data.get("session_id", "")
    except Exception:
        pass

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    tmp = tempfile.gettempdir()

    # Store session_id so other hooks can read it
    sid_file = os.path.join(tmp, f"claude-session-{h}.txt")
    with open(sid_file, "w") as f:
        f.write(session_id)

    # Clear stale tracking files
    for name in [
        f"claude-reads-{h}.txt",
        f"claude-tested-{h}.txt",
        f"claude-tested-files-{h}.txt",
        f"claude-violations-{h}.json",
        f"claude-override-{h}.json",
    ]:
        path = os.path.join(tmp, name)
        if os.path.exists(path):
            os.remove(path)

    # Log session start
    sessions_dir = os.path.join(proj_dir, ".claude", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    compliance = os.path.join(sessions_dir, "compliance.jsonl")

    entry = {
        "type": "session_start",
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "project_hash": h,
    }
    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    main()
