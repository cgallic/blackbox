#!/usr/bin/env python3
"""PostToolUse hook for Read: track which files have been read this session."""
import sys
import json
import os
import hashlib
import tempfile


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

    with open(reads_file, "a", encoding="utf-8") as f:
        f.write(fp + "\n")


if __name__ == "__main__":
    main()
