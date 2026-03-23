#!/usr/bin/env python3
"""PostToolUse hook for Edit: check if the edited file was read first."""
import sys
import json
import os
import hashlib
import tempfile
from datetime import datetime, timezone

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

    sessions_dir = os.path.join(proj_dir, ".claude", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    compliance = os.path.join(sessions_dir, "compliance.jsonl")

    entry = {
        "type": "edit_compliance",
        "ts": datetime.now(timezone.utc).isoformat(),
        "file": fp,
        "was_read_first": was_read,
    }
    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

if __name__ == "__main__":
    main()
