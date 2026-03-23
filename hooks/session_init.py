#!/usr/bin/env python3
"""SessionStart hook: reset ALL tracking temp files for this project."""
import os
import hashlib
import tempfile
import json
from datetime import datetime, timezone


def main():
    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    tmp = tempfile.gettempdir()

    # Clear ALL stale tracking files
    for name in [
        f"claude-reads-{h}.txt",
        f"claude-tested-{h}.txt",
        f"claude-violations-{h}.json",
        f"claude-override-{h}.json",
    ]:
        path = os.path.join(tmp, name)
        if os.path.exists(path):
            os.remove(path)

    # Log session start to compliance
    sessions_dir = os.path.join(proj_dir, ".claude", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    compliance = os.path.join(sessions_dir, "compliance.jsonl")

    entry = {
        "type": "session_start",
        "ts": datetime.now(timezone.utc).isoformat(),
        "project_hash": h,
    }
    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    main()
